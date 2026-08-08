#!/usr/bin/env python3
"""Почистить уже сохранённые тексты постпроцессингом OCR (без повторного OCR и без publish).

Примеры:
  python scripts/clean_ocr_text.py --dry-run --limit 100
  python scripts/clean_ocr_text.py --apply --limit 500
  python scripts/clean_ocr_text.py --apply --also-deltas --also-posts --batch-size 50
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import select  # noqa: E402

from explainlaw.db.models import NpaDelta, NpaDocument, NpaText, PostBank  # noqa: E402
from explainlaw.db.session import SessionLocal  # noqa: E402
from explainlaw.gates.text_checks import fix_ocr_artifacts, reflow_soft_linebreaks  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("clean_ocr_text")

_JUNK_RE = re.compile(r"[®°%`?'’′!]|(?<=\d):(?=\d)|\bдено\b", re.IGNORECASE)


def _needs_clean(text: str | None) -> bool:
    if not text:
        return False
    return _JUNK_RE.search(text) is not None


def _clean(text: str) -> str:
    return reflow_soft_linebreaks(fix_ocr_artifacts(text))


def _clean_delta_data(data: dict) -> tuple[dict, bool]:
    changed = False
    out = dict(data)
    changes = list(out.get("changes") or [])
    new_changes = []
    for ch in changes:
        item = dict(ch)
        for key in ("text_before", "text_after"):
            val = item.get(key)
            if isinstance(val, str) and _needs_clean(val):
                cleaned = _clean(val)
                if cleaned != val:
                    item[key] = cleaned
                    changed = True
        new_changes.append(item)
    if changed:
        out["changes"] = new_changes
    return out, changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean OCR artifacts in stored texts (no publish)")
    parser.add_argument("--limit", type=int, default=500, help="Max npa_text rows to update")
    parser.add_argument("--batch-size", type=int, default=40, help="Fetch/commit batch size")
    parser.add_argument("--dry-run", action="store_true", help="Only report, no writes")
    parser.add_argument("--apply", action="store_true", help="Write cleaned texts")
    parser.add_argument("--also-deltas", action="store_true", help="Also clean npa_delta.delta_data quotes")
    parser.add_argument("--also-posts", action="store_true", help="Also clean post_bank.content (no Telegram)")
    args = parser.parse_args()

    if args.dry_run == args.apply:
        print("Укажи ровно один режим: --dry-run или --apply", file=sys.stderr)
        return 2

    stats = {
        "texts_scanned": 0,
        "texts_dirty": 0,
        "texts_updated": 0,
        "deltas_updated": 0,
        "posts_updated": 0,
        "bytes_saved": 0,
    }
    samples: list[dict] = []

    with SessionLocal() as session:
        last_id = None
        clean_text_batches = 0
        while stats["texts_updated"] < args.limit:
            stmt = (
                select(NpaText, NpaDocument.eo_number)
                .join(NpaDocument, NpaDocument.id == NpaText.document_id)
                .order_by(NpaText.id.desc())
                .limit(args.batch_size)
            )
            if last_id is not None:
                stmt = stmt.where(NpaText.id < last_id)
            rows = session.execute(stmt).all()
            if not rows:
                break

            batch_updates = 0
            for text_row, eo in rows:
                last_id = text_row.id
                stats["texts_scanned"] += 1
                before = text_row.full_text or ""
                if not _needs_clean(before):
                    continue
                stats["texts_dirty"] += 1
                after = _clean(before)
                if after == before:
                    continue
                stats["bytes_saved"] += max(0, len(before) - len(after))
                if len(samples) < 8:
                    samples.append(
                        {
                            "eo_number": eo,
                            "before_preview": re.sub(r"\s+", " ", before)[:160],
                            "after_preview": re.sub(r"\s+", " ", after)[:160],
                        }
                    )
                stats["texts_updated"] += 1
                batch_updates += 1
                if args.apply:
                    text_row.full_text = after
                if stats["texts_updated"] >= args.limit:
                    break

            if args.apply and batch_updates:
                session.commit()
                logger.info(
                    "batch commit texts_updated=%s scanned=%s last_id=%s",
                    stats["texts_updated"],
                    stats["texts_scanned"],
                    last_id,
                )
                clean_text_batches = 0
            else:
                session.rollback()
                clean_text_batches += 1
                if clean_text_batches >= 40 and stats["texts_updated"] > 0:
                    logger.info("stop texts: %s clean batches after updates", clean_text_batches)
                    break
                if clean_text_batches >= 200 and stats["texts_updated"] == 0:
                    logger.info("stop texts: no dirty found")
                    break

            if len(rows) < args.batch_size:
                break

        if args.also_deltas:
            last_did = None
            delta_limit = args.limit * 3
            clean_batches = 0
            while stats["deltas_updated"] < delta_limit:
                stmt = select(NpaDelta).order_by(NpaDelta.id.desc()).limit(args.batch_size)
                if last_did is not None:
                    stmt = stmt.where(NpaDelta.id < last_did)
                deltas = list(session.execute(stmt).scalars())
                if not deltas:
                    break
                batch_u = 0
                for delta in deltas:
                    last_did = delta.id
                    data = delta.delta_data or {}
                    if not isinstance(data, dict):
                        continue
                    cleaned, changed = _clean_delta_data(data)
                    if not changed:
                        continue
                    stats["deltas_updated"] += 1
                    batch_u += 1
                    if args.apply:
                        delta.delta_data = cleaned
                    if stats["deltas_updated"] >= delta_limit:
                        break
                if args.apply and batch_u:
                    session.commit()
                    logger.info("batch commit deltas_updated=%s", stats["deltas_updated"])
                    clean_batches = 0
                else:
                    session.rollback()
                    clean_batches += 1
                    if clean_batches >= 25:
                        logger.info("stop deltas: %s clean batches in a row", clean_batches)
                        break
                if len(deltas) < args.batch_size:
                    break

        if args.also_posts:
            posts = list(
                session.execute(select(PostBank).order_by(PostBank.id.desc()).limit(args.limit)).scalars()
            )
            for post in posts:
                if not _needs_clean(post.content or ""):
                    continue
                cleaned = _clean(post.content)
                if cleaned == post.content:
                    continue
                stats["posts_updated"] += 1
                if args.apply:
                    post.content = cleaned
            if args.apply and stats["posts_updated"]:
                session.commit()
                logger.info("committed posts_updated=%s", stats["posts_updated"])
            else:
                session.rollback()

    print(
        json.dumps(
            {"mode": "apply" if args.apply else "dry-run", "stats": stats, "samples": samples},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

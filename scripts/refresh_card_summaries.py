#!/usr/bin/env python3
"""Перегенерировать title+summary документов через LLM (без OCR, без post_bank, без Telegram).

Пишет только npa_summary. Текст карточки собирается при publish из сводки+дельты.

Примеры:
  python scripts/refresh_card_summaries.py --dry-run --limit 20
  python scripts/refresh_card_summaries.py --apply --limit 3
  python scripts/refresh_card_summaries.py --apply --limit 6000
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

_YANDEX_DB_HOST = "rc1b-1g6jop7qtr87ir0o.mdb.yandexcloud.net"
_YANDEX_DB_IP = "89.169.176.138"


def _preload_env(env_file: Path | None = None) -> None:
    path = env_file
    if path is None:
        for candidate in (ROOT / ".env.yandex.local", ROOT / ".env"):
            if candidate.exists():
                path = candidate
                break
    if path is None or not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key] = value.strip().strip('"').strip("'")
    url = os.environ.get("DATABASE_URL", "")
    if _YANDEX_DB_HOST in url:
        os.environ["DATABASE_URL"] = url.replace(_YANDEX_DB_HOST, _YANDEX_DB_IP)


_preload_env()

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from explainlaw.config import settings  # noqa: E402
from explainlaw.db.models import (  # noqa: E402
    NpaDelta,
    NpaDocument,
    NpaSummary,
    PostBank,
    PostItem,
    PostType,
)
from explainlaw.db.session import SessionLocal  # noqa: E402
from explainlaw.extraction.fragment import extract_summary_fragment  # noqa: E402
from explainlaw.gates.post_bank import format_post_title  # noqa: E402
from explainlaw.llm.factory import create_gateway_client, create_qwen_client  # noqa: E402
from explainlaw.llm.gateway import generate_summary, needs_gist_refresh  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("refresh_card_summaries")


def _rebuild_digests(session, changed_doc_ids: set[int], *, apply: bool, stats: dict) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "rebuild_post_bank_content", ROOT / "scripts" / "rebuild_post_bank_content.py"
    )
    if spec is None or spec.loader is None:
        logger.error("не удалось загрузить rebuild_post_bank_content.py")
        return
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    changed_docs = {doc_id: {"post_id": 0} for doc_id in changed_doc_ids}
    module._rebuild_digests(
        session,
        changed_docs=changed_docs,
        batch_size=40,
        apply=apply,
        stats=stats,
        samples=[],
        force=True,
    )


def _generate_with_retry(*, retries: int, sleep_sec: float, **kwargs):
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return generate_summary(**kwargs)
        except Exception as exc:
            last_error = exc
            wait = sleep_sec * attempt
            logger.warning("gateway attempt %s/%s failed: %s; sleep %.1fs", attempt, retries, exc, wait)
            time.sleep(wait)
    raise last_error or RuntimeError("gateway failed")


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh card titles/summaries via Gateway (no OCR, no Telegram)")
    parser.add_argument("--limit", type=int, default=5000, help="Max cards to send to Gateway")
    parser.add_argument("--batch-size", type=int, default=20, help="Fetch/commit batch size")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--force", action="store_true", help="Refresh even cards that already look like 1b")
    parser.add_argument("--after-post-id", type=int, default=None, help="Resume: only posts with id < this")
    parser.add_argument("--sleep", type=float, default=0.05, help="Pause between Gateway calls")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--also-digests", action="store_true")
    parser.add_argument("--env-file", type=str, default=None)
    args = parser.parse_args()

    if args.env_file:
        _preload_env(Path(args.env_file))

    if args.dry_run == args.apply:
        print("Укажи ровно один режим: --dry-run или --apply", file=sys.stderr)
        return 2

    gateway = create_gateway_client()
    qwen = create_qwen_client()
    if args.apply and not gateway.available and not qwen.available:
        print("Нет LLM: задай GATEWAY_API_BASE или Qwen/Kafka", file=sys.stderr)
        return 2
    logger.info(
        "llm gateway=%s qwen=%s transport=%s",
        bool(gateway.available),
        bool(qwen.available),
        settings.llm_transport,
    )

    stats = {
        "scanned": 0,
        "skipped_good": 0,
        "skipped_missing": 0,
        "would_refresh": 0,
        "refreshed": 0,
        "insufficient": 0,
        "errors": 0,
        "digests_scanned": 0,
        "digests_dirty": 0,
        "digests_updated": 0,
    }
    samples: list[dict] = []
    changed_doc_ids: set[int] = set()

    with SessionLocal() as session:
        last_id = args.after_post_id
        refreshed_in_limit = 0

        while refreshed_in_limit < args.limit:
            stmt = (
                select(PostItem, PostBank)
                .join(PostBank, PostBank.id == PostItem.post_id)
                .where(PostBank.post_type == PostType.single)
                .order_by(PostBank.id.desc())
                .limit(args.batch_size)
            )
            if last_id is not None:
                stmt = stmt.where(PostBank.id < last_id)
            rows = session.execute(stmt).all()
            if not rows:
                break

            batch_updates = 0
            for item, post in rows:
                last_id = post.id
                stats["scanned"] += 1

                if refreshed_in_limit >= args.limit:
                    break

                doc = session.execute(
                    select(NpaDocument)
                    .options(
                        selectinload(NpaDocument.enactments),
                        selectinload(NpaDocument.text),
                        selectinload(NpaDocument.delta),
                    )
                    .where(NpaDocument.id == item.document_id)
                ).scalar_one_or_none()
                summary = session.execute(
                    select(NpaSummary)
                    .where(NpaSummary.document_id == item.document_id)
                    .order_by(NpaSummary.id.desc())
                    .limit(1)
                ).scalar_one_or_none()
                delta = doc.delta if doc else None
                full_text = doc.text.full_text if doc and doc.text else ""

                if not doc or not delta or not summary or not (full_text or "").strip():
                    stats["skipped_missing"] += 1
                    continue

                if not args.force and not needs_gist_refresh(title=summary.title, summary_text=summary.summary_text):
                    stats["skipped_good"] += 1
                    continue

                stats["would_refresh"] += 1
                refreshed_in_limit += 1
                fragment = extract_summary_fragment(full_text)
                changes = (delta.delta_data or {}).get("changes")

                if not args.apply:
                    if len(samples) < 8:
                        samples.append(
                            {
                                "post_id": post.id,
                                "eo_number": doc.eo_number,
                                "old_title": (summary.title or "")[:120],
                                "old_summary": re_preview(summary.summary_text),
                            }
                        )
                    continue

                try:
                    result = _generate_with_retry(
                        retries=args.retries,
                        sleep_sec=max(args.sleep, 0.2),
                        number=doc.number,
                        document_date=doc.document_date.isoformat() if doc.document_date else None,
                        name=doc.name,
                        fragment=fragment,
                        changes=changes,
                    )
                except Exception:
                    stats["errors"] += 1
                    logger.exception("gateway failed eo=%s post_id=%s", doc.eo_number, post.id)
                    continue

                if result.text.upper().startswith("НЕДОСТАТОЧНО ДАННЫХ"):
                    stats["insufficient"] += 1
                    logger.info("skip insufficient eo=%s post_id=%s", doc.eo_number, post.id)
                    continue

                summary.summary_text = result.text
                summary.title = result.title
                summary.model_route = result.model_route
                new_title = format_post_title(doc, summary)
                changed_doc_ids.add(doc.id)
                stats["refreshed"] += 1
                batch_updates += 1
                if len(samples) < 8:
                    samples.append(
                        {
                            "post_id": post.id,
                            "eo_number": doc.eo_number,
                            "new_title": new_title,
                            "new_summary": re_preview(result.text),
                        }
                    )
                logger.info("refreshed eo=%s post_id=%s title=%s", doc.eo_number, post.id, new_title)
                if args.sleep:
                    time.sleep(args.sleep)

            if args.apply and batch_updates:
                session.commit()
                logger.info("batch commit refreshed=%s scanned=%s", stats["refreshed"], stats["scanned"])
            else:
                session.rollback()

            if len(rows) < args.batch_size:
                break

        if args.also_digests and changed_doc_ids:
            _rebuild_digests(session, changed_doc_ids, apply=args.apply, stats=stats)
            if args.apply:
                session.commit()

    print(json.dumps({"mode": "apply" if args.apply else "dry-run", "stats": stats, "samples": samples}, ensure_ascii=False, indent=2))
    return 1 if stats["errors"] and stats["refreshed"] == 0 else 0


def re_preview(text: str | None) -> str:
    return " ".join((text or "").split())[:180]


if __name__ == "__main__":
    raise SystemExit(main())

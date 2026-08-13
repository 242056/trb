#!/usr/bin/env python3
"""Пересобрать content уже сохранённых post_bank карточек через исправленный
format_card_content (лимит цитаты — без повторной публикации в Telegram/Kafka).

Фаза 1 — одиночные карточки (post_type=single): пересчитать content из
document + delta + summary.
Фаза 2 (--also-digests) — дайджесты (post_type in digest, mini_digest),
ссылающиеся на документы, чьи одиночные карточки изменились в Фазе 1:
пересобрать пронумерованные блоки, используя уже исправленный контент.

Примеры:
  python scripts/rebuild_post_bank_content.py --dry-run --also-digests
  python scripts/rebuild_post_bank_content.py --apply --also-digests --limit 5000
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

from sqlalchemy import select, text  # noqa: E402

from explainlaw.db.models import (  # noqa: E402
    NpaDelta,
    NpaDocument,
    NpaSummary,
    NpaText,
    PostBank,
    PostItem,
    PostType,
)
from explainlaw.db.session import SessionLocal  # noqa: E402
from explainlaw.delta.builder import build_delta_for_document  # noqa: E402
from explainlaw.gates.post_bank import format_card_content  # noqa: E402
from explainlaw.gates.text_checks import reflow_soft_linebreaks  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("rebuild_post_bank_content")


_DIRTY_DELTA_SQL = text(
    """
    EXISTS (
      SELECT 1
      FROM jsonb_array_elements(COALESCE(npa_delta.delta_data->'changes', '[]'::jsonb)) ch
      WHERE length(COALESCE(ch->>'text_after', '')) > 2000
         OR length(COALESCE(ch->>'text_before', '')) > 2000
    )
    """
)


def _rebuild_deltas(session, *, limit: int, batch_size: int, apply: bool, only_dirty: bool, stats: dict) -> None:
    """Пересобрать npa_delta из norm_change_event (без повторного OCR)."""
    last_id = None
    processed = 0

    while processed < limit:
        stmt = (
            select(NpaDocument, NpaText, NpaDelta)
            .join(NpaText, NpaText.document_id == NpaDocument.id)
            .join(NpaDelta, NpaDelta.document_id == NpaDocument.id)
            .where(
                NpaDocument.name.ilike("%внесении изменен%")
                | NpaDocument.name.ilike("%внесении изменений%")
            )
            .order_by(NpaDocument.id.desc())
            .limit(batch_size)
        )
        if only_dirty:
            stmt = stmt.where(_DIRTY_DELTA_SQL)
        if last_id is not None:
            stmt = stmt.where(NpaDocument.id < last_id)
        rows = session.execute(stmt).all()
        if not rows:
            break

        batch_updates = 0
        for doc, text_row, delta_row in rows:
            last_id = doc.id
            processed += 1
            stats["deltas_scanned"] += 1
            old_data = delta_row.delta_data
            before_changes = len((old_data or {}).get("changes") or [])

            rebuilt = build_delta_for_document(session, doc, text_row.full_text or "")
            if not rebuilt or rebuilt.delta_data == old_data:
                continue

            after_changes = len((rebuilt.delta_data or {}).get("changes") or [])
            stats["deltas_dirty"] += 1
            logger.info(
                "delta %s eo=%s changes %s→%s",
                "update" if apply else "would update",
                doc.eo_number,
                before_changes,
                after_changes,
            )
            if apply:
                batch_updates += 1
                stats["deltas_updated"] += 1

            if processed >= limit:
                break

        if apply and batch_updates:
            session.commit()
            logger.info("batch commit deltas_updated=%s processed=%s", stats["deltas_updated"], processed)
        else:
            session.rollback()

        if len(rows) < batch_size:
            break


def _rebuild_single_cards(
    session, *, limit: int, batch_size: int, apply: bool, only_dirty: bool, stats: dict, samples: list
) -> dict:
    """post_id -> {eo_number, before_len, after_len} для изменившихся одиночных карточек."""
    changed_docs: dict[int, dict] = {}
    last_id = None
    processed = 0

    while processed < limit:
        stmt = (
            select(PostItem, PostBank)
            .join(PostBank, PostBank.id == PostItem.post_id)
            .where(PostBank.post_type == PostType.single)
            .order_by(PostBank.id.desc())
            .limit(batch_size)
        )
        if only_dirty:
            stmt = stmt.where(text("length(post_bank.content) > 2000"))
        if last_id is not None:
            stmt = stmt.where(PostBank.id < last_id)
        rows = session.execute(stmt).all()
        if not rows:
            break

        batch_updates = 0
        for item, post in rows:
            last_id = post.id
            processed += 1
            stats["single_scanned"] += 1

            doc = session.get(NpaDocument, item.document_id)
            delta = session.execute(
                select(NpaDelta).where(NpaDelta.document_id == item.document_id)
            ).scalar_one_or_none()
            summary = session.execute(
                select(NpaSummary)
                .where(NpaSummary.document_id == item.document_id)
                .order_by(NpaSummary.id.asc())
                .limit(1)
            ).scalar_one_or_none()

            if not doc or not delta or not summary:
                continue

            new_content = format_card_content(doc, summary, delta)
            before = post.content or ""
            if new_content == before:
                continue

            stats["single_dirty"] += 1
            changed_docs[item.document_id] = {
                "post_id": post.id,
                "eo_number": doc.eo_number,
                "before_len": len(before),
                "after_len": len(new_content),
            }
            if len(samples) < 10:
                samples.append(
                    {
                        "post_id": post.id,
                        "eo_number": doc.eo_number,
                        "before_len": len(before),
                        "after_len": len(new_content),
                        "before_preview": re.sub(r"\s+", " ", before)[:160],
                        "after_preview": re.sub(r"\s+", " ", new_content)[:160],
                    }
                )
            if apply:
                post.content = new_content
                stats["single_updated"] += 1
                batch_updates += 1

            if processed >= limit:
                break

        if apply and batch_updates:
            session.commit()
            logger.info("batch commit single_updated=%s processed=%s", stats["single_updated"], processed)
        else:
            session.rollback()

        if len(rows) < batch_size:
            break

    return changed_docs


def _single_card_content(session, doc_id: int, cache: dict) -> tuple[NpaDocument, str] | None:
    """Текущее содержимое одиночной карточки документа (уже исправленное или неизменное)."""
    if doc_id in cache:
        return cache[doc_id]
    row = session.execute(
        select(NpaDocument, PostBank.content)
        .join(PostItem, PostItem.document_id == NpaDocument.id)
        .join(PostBank, PostBank.id == PostItem.post_id)
        .where(NpaDocument.id == doc_id, PostBank.post_type == PostType.single)
        .limit(1)
    ).first()
    if row is None:
        cache[doc_id] = None
        return None
    doc, content = row
    cache[doc_id] = (doc, content or "")
    return cache[doc_id]


def _rebuild_digest(post: PostBank, item_document_ids: list[int], changed_docs: dict, cache: dict) -> str | None:
    """Пересобрать content дайджеста, если хотя бы один пункт изменился."""
    if not any(doc_id in changed_docs for doc_id in item_document_ids):
        return None

    header_match = re.match(r"^.*\n", post.content or "")
    header = header_match.group(0).rstrip("\n") if header_match else (post.content or "").split("\n", 1)[0]

    lines = [header, ""]
    idx = 0
    for doc_id in item_document_ids:
        cached = cache.get(doc_id)
        if cached is None:
            continue
        doc, card_content = cached
        idx += 1
        num = doc.number or "—"
        title = doc.name or doc.eo_number or ""
        lines.append(f"{idx}. №{num} — {title}")
        lines.append(reflow_soft_linebreaks(card_content.strip()))
        if doc.source_url:
            lines.append(f"Источник: {doc.source_url}")
        lines.append("")
    return "\n".join(lines).strip()


def _rebuild_digests(session, *, changed_docs: dict, batch_size: int, apply: bool, stats: dict, samples: list) -> None:
    doc_cache: dict[int, tuple[NpaDocument, str] | None] = {}
    for doc_id, info in changed_docs.items():
        doc = session.get(NpaDocument, doc_id)
        post = session.get(PostBank, info["post_id"])
        if doc and post:
            doc_cache[doc_id] = (doc, post.content or "")

    last_id = None
    while True:
        stmt = (
            select(PostBank)
            .where(PostBank.post_type.in_([PostType.digest, PostType.mini_digest]))
            .order_by(PostBank.id.desc())
            .limit(batch_size)
        )
        if last_id is not None:
            stmt = stmt.where(PostBank.id < last_id)
        posts = list(session.execute(stmt).scalars())
        if not posts:
            break

        batch_updates = 0
        for post in posts:
            last_id = post.id
            stats["digests_scanned"] += 1

            items = list(
                session.execute(
                    select(PostItem)
                    .where(PostItem.post_id == post.id)
                    .order_by(PostItem.order_index.asc())
                ).scalars()
            )
            doc_ids = [it.document_id for it in items]
            if not any(doc_id in changed_docs for doc_id in doc_ids):
                continue
            for doc_id in doc_ids:
                _single_card_content(session, doc_id, doc_cache)

            new_content = _rebuild_digest(post, doc_ids, changed_docs, doc_cache)
            if new_content is None or new_content == post.content:
                continue

            stats["digests_dirty"] += 1
            if len(samples) < 10:
                samples.append(
                    {
                        "post_id": post.id,
                        "post_type": post.post_type.value,
                        "status": post.status.value,
                        "before_len": len(post.content or ""),
                        "after_len": len(new_content),
                    }
                )
            if apply:
                post.content = new_content
                stats["digests_updated"] += 1
                batch_updates += 1

        if apply and batch_updates:
            session.commit()
            logger.info("batch commit digests_updated=%s", stats["digests_updated"])
        else:
            session.rollback()

        if len(posts) < batch_size:
            break


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild stored post_bank content (no publish)")
    parser.add_argument("--limit", type=int, default=5000, help="Max single-card post_bank rows to scan")
    parser.add_argument("--batch-size", type=int, default=40, help="Fetch/commit batch size")
    parser.add_argument("--dry-run", action="store_true", help="Only report, no writes")
    parser.add_argument("--apply", action="store_true", help="Write rebuilt content")
    parser.add_argument("--also-digests", action="store_true", help="Also rebuild digests referencing changed docs")
    parser.add_argument(
        "--also-rebuild-deltas",
        action="store_true",
        help="First rebuild npa_delta from events (skip baseline, cap quotes)",
    )
    parser.add_argument(
        "--only-dirty",
        action="store_true",
        help="Only deltas/cards with oversized quotes or content (>2000 chars)",
    )
    args = parser.parse_args()

    if args.dry_run == args.apply:
        print("Укажи ровно один режим: --dry-run или --apply", file=sys.stderr)
        return 2

    stats = {
        "deltas_scanned": 0,
        "deltas_dirty": 0,
        "deltas_updated": 0,
        "single_scanned": 0,
        "single_dirty": 0,
        "single_updated": 0,
        "digests_scanned": 0,
        "digests_dirty": 0,
        "digests_updated": 0,
    }
    samples: list[dict] = []

    with SessionLocal() as session:
        if args.also_rebuild_deltas:
            _rebuild_deltas(
                session,
                limit=args.limit,
                batch_size=args.batch_size,
                apply=args.apply,
                only_dirty=args.only_dirty,
                stats=stats,
            )

        changed_docs = _rebuild_single_cards(
            session,
            limit=args.limit,
            batch_size=args.batch_size,
            apply=args.apply,
            only_dirty=args.only_dirty,
            stats=stats,
            samples=samples,
        )
        logger.info("single cards changed: %s", len(changed_docs))

        if args.also_digests and changed_docs:
            _rebuild_digests(
                session, changed_docs=changed_docs, batch_size=args.batch_size, apply=args.apply, stats=stats, samples=samples
            )

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

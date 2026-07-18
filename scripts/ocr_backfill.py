#!/usr/bin/env python3
"""Переизвлечение текста OCR для документов с коротким/пустым текстом или сканами."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import or_, select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from explainlaw.config import settings  # noqa: E402
from explainlaw.db.models import NpaDocument, NpaText, RawFileType, TextExtractionMethod  # noqa: E402
from explainlaw.db.session import SessionLocal  # noqa: E402
from explainlaw.extraction.pdf_extractor import extract_text_from_pdf  # noqa: E402
from explainlaw.storage.object_store import get_storage  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ocr_backfill")


def main() -> int:
    parser = argparse.ArgumentParser(description="OCR backfill for short/scan texts")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument(
        "--min-chars",
        type=int,
        default=settings.ocr_text_threshold,
        help="ПереOCR если текст короче порога",
    )
    parser.add_argument(
        "--only-pdf-text",
        action="store_true",
        help="Только документы, ранее извлечённые без OCR",
    )
    args = parser.parse_args()

    # OCR должен быть включён для этого скрипта
    settings.ocr_enabled = True

    storage = get_storage()
    stats = {"candidates": 0, "updated": 0, "skipped": 0, "errors": 0}

    with SessionLocal() as session:
        stmt = (
            select(NpaDocument)
            .options(selectinload(NpaDocument.raw_files), selectinload(NpaDocument.text))
            .join(NpaText, NpaText.document_id == NpaDocument.id)
            .where(
                or_(
                    NpaText.full_text.is_(None),
                    NpaText.full_text == "",
                )
            )
            .order_by(NpaDocument.publish_date_short.asc())
            .limit(args.limit)
        )
        # Также короткие тексты
        short_stmt = (
            select(NpaDocument)
            .options(selectinload(NpaDocument.raw_files), selectinload(NpaDocument.text))
            .join(NpaText, NpaText.document_id == NpaDocument.id)
            .where(NpaText.full_text.is_not(None))
            .order_by(NpaDocument.publish_date_short.asc())
            .limit(args.limit * 3)
        )
        docs = list(session.execute(stmt).scalars().unique().all())
        for doc in session.execute(short_stmt).scalars().unique().all():
            if doc in docs:
                continue
            text = (doc.text.full_text or "") if doc.text else ""
            if len(text.strip()) >= args.min_chars:
                continue
            if args.only_pdf_text and doc.text and doc.text.extraction_method != TextExtractionMethod.pdf_text:
                continue
            docs.append(doc)
            if len(docs) >= args.limit:
                break

        stats["candidates"] = len(docs)
        for doc in docs:
            pdf_raw = next((r for r in doc.raw_files if r.raw_type == RawFileType.pdf), None)
            if pdf_raw is None:
                stats["skipped"] += 1
                continue
            try:
                pdf_bytes = storage.get_by_path(pdf_raw.storage_path)
                result = extract_text_from_pdf(pdf_bytes)
                if not result.text or len(result.text.strip()) < len(
                    (doc.text.full_text or "").strip()
                ):
                    stats["skipped"] += 1
                    continue
                doc.text.full_text = result.text
                doc.text.extraction_method = result.method
                doc.text.page_count_extracted = result.page_count
                session.commit()
                stats["updated"] += 1
                logger.info("OCR ok %s (%s, %d chars)", doc.eo_number, result.method, len(result.text))
            except Exception:
                session.rollback()
                stats["errors"] += 1
                logger.exception("OCR fail %s", doc.eo_number)

    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0 if stats["errors"] == 0 or stats["updated"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

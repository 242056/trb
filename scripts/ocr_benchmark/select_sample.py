#!/usr/bin/env python3
"""Этап 1 ручного OCR-бенчмарка: пул кандидатов для последующей визуальной разметки человеком.

Формирует ~50-60 кандидатов, разложенных по осям (эра публикации × длина документа),
и пишет data/candidate_pool.csv с пустыми колонками has_tables/scan_quality/include/notes —
дальше пользователь открывает PDF каждого кандидата, заполняет эти колонки, сокращает
пул до 20-30 итоговых строк и сохраняет результат как sample_manifest.csv (см. README.md).
"""

import argparse
import logging
from collections import defaultdict
from pathlib import Path

from common import CANDIDATE_POOL_CSV, SampleCandidate, era_bucket, length_bucket, write_candidates_csv

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from explainlaw.db.models import NpaDocument, RawFileType
from explainlaw.db.session import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("select_sample")

# "extreme(>300)" исключаем из пула по умолчанию — полный OCR-прогон занял бы часы,
# а медиана документов в БД — 4 страницы, экстремумы (до 6404 стр.) не репрезентативны.
SKIP_LENGTH_BUCKETS = {"extreme(>300)"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Пул кандидатов для ручного OCR-бенчмарка")
    parser.add_argument("--per-cell", type=int, default=6, help="Максимум кандидатов на ячейку эра×длина")
    parser.add_argument("--out", default=str(CANDIDATE_POOL_CSV))
    args = parser.parse_args()

    with SessionLocal() as session:
        stmt = (
            select(NpaDocument)
            .options(selectinload(NpaDocument.raw_files), selectinload(NpaDocument.text))
            .order_by(NpaDocument.document_date.asc())
        )
        docs = list(session.execute(stmt).scalars().unique().all())

    by_cell: dict[tuple[str, str], list[SampleCandidate]] = defaultdict(list)
    for doc in docs:
        pdf_raw = next((r for r in doc.raw_files if r.raw_type == RawFileType.pdf), None)
        if pdf_raw is None:
            continue
        lb = length_bucket(doc.pages_count)
        if lb in SKIP_LENGTH_BUCKETS:
            continue
        eb = era_bucket(doc.document_date)
        cell = (eb, lb)
        if len(by_cell[cell]) >= args.per_cell:
            continue
        by_cell[cell].append(
            SampleCandidate(
                eo_number=doc.eo_number,
                number=doc.number or "",
                document_date=doc.document_date.isoformat() if doc.document_date else "",
                pages_count=doc.pages_count or 0,
                extraction_method=(doc.text.extraction_method.value if doc.text else ""),
                pdf_storage_path=pdf_raw.storage_path,
                era_bucket=eb,
                length_bucket=lb,
            )
        )

    candidates = [c for cell in sorted(by_cell) for c in by_cell[cell]]
    write_candidates_csv(Path(args.out), candidates)

    logger.info("Кандидатов: %d", len(candidates))
    for cell in sorted(by_cell):
        logger.info("  %s x %s: %d", cell[0], cell[1], len(by_cell[cell]))
    if not candidates:
        logger.warning("Пул пуст — проверьте доступ к БД / фильтры")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

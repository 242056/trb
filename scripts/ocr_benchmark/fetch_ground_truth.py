#!/usr/bin/env python3
"""Этап 3 ручного OCR-бенчмарка: черновик эталона из уже прогнанного OCR + статус вычитки.

Черновик эталона берётся из вывода run_ocr.py для одного «чернового» движка (по умолчанию
tesseract), НЕ с pravo.gov.ru — see «Находка при верификации» в плане: ни page_snapshot, ни
zip не содержат независимого текстового слоя. Человек затем открывает `<eo>.draft.txt` рядом
с самим PDF-сканом и вычитывает против него, отдельно и внимательно сверяя каждое число/дату/
номер статьи-пункта/сумму (не только читаемость) — иначе ошибка чернового движка может попасть
в эталон незамеченной и дать этому движку завышенную оценку в §4.2 (см. явный риск в плане).
Результат вычитки сохраняется человеком как `<eo>.reviewed.txt`; только этот файл используется
compute_metrics.py — `.draft.txt` эталоном никогда не считается.
"""

import argparse
import logging

from common import (
    DRAFT_ENGINE_DEFAULT,
    included_manifest,
    ocr_cleaned_path,
    pdf_cache_path,
    ground_truth_draft_path,
    ground_truth_reviewed_path,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("fetch_ground_truth")


def main() -> int:
    parser = argparse.ArgumentParser(description="Черновик эталона из вывода run_ocr.py + статус вычитки")
    parser.add_argument("--draft-engine", default=DRAFT_ENGINE_DEFAULT, help="Движок-источник черновика")
    parser.add_argument("--eo", action="append", help="Ограничить конкретными eo_number (можно несколько раз)")
    parser.add_argument("--force", action="store_true", help="Перезаписать уже существующий .draft.txt")
    parser.add_argument(
        "--status", action="store_true", help="Только показать статус вычитки по выборке, ничего не писать"
    )
    args = parser.parse_args()

    candidates = included_manifest()
    if args.eo:
        wanted = set(args.eo)
        candidates = [c for c in candidates if c.eo_number in wanted]
    if not candidates:
        logger.error("Пустая выборка (sample_manifest.csv с include=true, либо --eo не совпал)")
        return 1

    stats = {"documents": 0, "already_reviewed": 0, "drafts_written": 0, "pending_review": 0, "missing_source": 0}

    for candidate in candidates:
        stats["documents"] += 1
        eo = candidate.eo_number
        reviewed_path = ground_truth_reviewed_path(eo)

        if reviewed_path.exists():
            stats["already_reviewed"] += 1
            logger.info("%s: вычитан (%s)", eo, reviewed_path.name)
            continue

        if args.status:
            has_draft = ground_truth_draft_path(eo).exists()
            stats["pending_review"] += 1
            logger.info("%s: черновик %s, вычитка НЕ готова", eo, "есть" if has_draft else "ОТСУТСТВУЕТ")
            continue

        source_path = ocr_cleaned_path(eo, args.draft_engine)
        if not source_path.exists():
            logger.error(
                "%s: нет %s — сначала прогоните `run_ocr.py --engines %s --eo %s`",
                eo,
                source_path,
                args.draft_engine,
                eo,
            )
            stats["missing_source"] += 1
            continue

        draft_path = ground_truth_draft_path(eo)
        if draft_path.exists() and not args.force:
            logger.info("%s: черновик уже есть (%s), вычитка не готова — пропускаю", eo, draft_path.name)
            stats["pending_review"] += 1
            continue

        draft_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
        stats["drafts_written"] += 1
        stats["pending_review"] += 1
        logger.info(
            "%s: черновик готов — %s.\n"
            "    Откройте рядом с PDF (%s), вычитайте против скана (отдельно сверьте числа/даты/\n"
            "    номера статей-пунктов/суммы!) и сохраните результат как %s",
            eo,
            draft_path,
            pdf_cache_path(eo),
            reviewed_path.name,
        )

    logger.info("Итого: %s", stats)
    return 0 if stats["missing_source"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

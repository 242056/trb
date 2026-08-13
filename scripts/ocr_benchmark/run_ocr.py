#!/usr/bin/env python3
"""Этап 2 ручного OCR-бенчмарка: прогон нескольких OCR-движков по PDF из sample_manifest.csv.

Инстанцирует движки напрямую (Tesseract, PaddleOCR, PyMuPDF-native) — не через
get_ocr_engine(), который выбирает только один. Yandex Vision исключён по решению
пользователя. Для каждого (документ, движок) пишет два файла в data/ocr/<eo>/:
  <engine>.raw.txt      — необработанный вывод, склеенный по страницам
  <engine>.cleaned.txt  — reflow_soft_linebreaks + strip_signature_block (эквивалент
                          продовой _normalize_text)

Полный прогон по всем страницам без обрезки (по решению пользователя) — для документов
из бакета long(31-300) может занять существенное время; прогресс логируется по страницам,
повторный запуск с тем же движком для документа, у которого уже есть .raw.txt, пропускается
(если не передан --force).
"""

import argparse
import logging
import time

from common import (
    fetch_pdf_bytes,
    included_manifest,
    ocr_cleaned_path,
    ocr_raw_path,
)

import fitz

from explainlaw.extraction.ocr_engines import PaddleEngine, TesseractEngine
from explainlaw.gates.text_checks import reflow_soft_linebreaks, strip_signature_block
from explainlaw.storage.object_store import get_storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("run_ocr")

PAGE_LOG_EVERY = 10


class PyMuPdfNativeEngine:
    """OCR через встроенный в PyMuPDF textpage_ocr (тот же Tesseract под капотом, другой путь)."""

    name = "pymupdf"

    def page_to_text(self, page: "fitz.Page") -> str:
        textpage = page.get_textpage_ocr(language="rus", dpi=200, full=True)
        return page.get_text(textpage=textpage)


def _clean(raw: str) -> str:
    return strip_signature_block(reflow_soft_linebreaks(raw))


def run_engine_on_pdf(engine_name: str, doc: "fitz.Document", engine_obj) -> str:
    chunks: list[str] = []
    total = doc.page_count
    for idx, page in enumerate(doc, start=1):
        if engine_name == "pymupdf":
            text = engine_obj.page_to_text(page)
        else:
            pix = page.get_pixmap(dpi=200)
            text = engine_obj.image_to_text(pix.tobytes("jpeg"))
        chunks.append(text or "")
        if idx % PAGE_LOG_EVERY == 0 or idx == total:
            logger.info("    %s: стр. %d/%d", engine_name, idx, total)
    return "\n\n".join(chunks)


def build_engines(names: list[str]) -> dict:
    registry = {
        "tesseract": TesseractEngine(),
        "paddle": PaddleEngine(),
        "pymupdf": PyMuPdfNativeEngine(),
    }
    engines = {}
    for name in names:
        eng = registry.get(name)
        if eng is None:
            raise ValueError(f"Неизвестный движок: {name}")
        if name != "pymupdf" and not eng.available():
            logger.warning("Движок %s недоступен в этом окружении — пропускаю", name)
            continue
        engines[name] = eng
    return engines


def main() -> int:
    parser = argparse.ArgumentParser(description="Прогон OCR-движков по выборке бенчмарка")
    parser.add_argument(
        "--engines",
        default="tesseract,pymupdf",
        help="paddle доступен флагом, но по умолчанию исключён — см. README (paddleocr 3.x "
        "в этом окружении несовместим с продовым PaddleEngine, написанным для 2.x API)",
    )
    parser.add_argument("--eo", action="append", help="Ограничить конкретными eo_number (можно несколько раз)")
    parser.add_argument("--force", action="store_true", help="Перегнать даже если raw.txt уже существует")
    args = parser.parse_args()

    engine_names = [e.strip() for e in args.engines.split(",") if e.strip()]
    engines = build_engines(engine_names)
    if not engines:
        logger.error("Ни один запрошенный движок не доступен")
        return 1

    candidates = included_manifest()
    if args.eo:
        wanted = set(args.eo)
        candidates = [c for c in candidates if c.eo_number in wanted]
    if not candidates:
        logger.error("Пустая выборка (sample_manifest.csv с include=true, либо --eo не совпал)")
        return 1

    storage = get_storage()
    stats = {"documents": 0, "runs": 0, "skipped": 0, "errors": 0}

    for candidate in candidates:
        stats["documents"] += 1
        pdf_bytes = fetch_pdf_bytes(storage, candidate)
        fitz_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            for engine_name, engine_obj in engines.items():
                raw_path = ocr_raw_path(candidate.eo_number, engine_name)
                if raw_path.exists() and not args.force:
                    logger.info("skip %s/%s (уже есть)", candidate.eo_number, engine_name)
                    stats["skipped"] += 1
                    continue
                logger.info(
                    "OCR %s [%s] через %s (%d стр.)",
                    candidate.eo_number,
                    candidate.number,
                    engine_name,
                    fitz_doc.page_count,
                )
                started = time.monotonic()
                try:
                    raw_text = run_engine_on_pdf(engine_name, fitz_doc, engine_obj)
                except Exception:
                    logger.exception("OCR fail %s/%s", candidate.eo_number, engine_name)
                    stats["errors"] += 1
                    continue
                raw_path.write_text(raw_text, encoding="utf-8")
                ocr_cleaned_path(candidate.eo_number, engine_name).write_text(_clean(raw_text), encoding="utf-8")
                stats["runs"] += 1
                logger.info(
                    "  -> %d симв., %.1fс", len(raw_text), time.monotonic() - started
                )
        finally:
            fitz_doc.close()

    logger.info("Итого: %s", stats)
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

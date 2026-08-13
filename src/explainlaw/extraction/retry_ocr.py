"""Повторное извлечение текста для документов, уже провалившихся на quality-гейте.

Отдельная от `pdf_extractor.py` реализация — не горячий путь, вызывается только для
документов, уже помеченных подозрительными: сохраняет постраничные границы, необходимые для
безопасной LLM-очистки (`extraction/llm_cleanup.py`), в отличие от `_ocr_pdf_pages`, которая
сразу склеивает страницы в одну строку.
"""

from __future__ import annotations

import logging

import fitz

from explainlaw.extraction.llm_cleanup import clean_page_with_safety_net
from explainlaw.extraction.ocr_engines import get_ocr_engine
from explainlaw.extraction.quality import is_text_unreadable
from explainlaw.gates.text_checks import reflow_soft_linebreaks, strip_signature_block

logger = logging.getLogger(__name__)


def retry_extract_with_llm_cleanup(pdf_bytes: bytes) -> tuple[str, bool]:
    """Возвращает (текст, still_unreadable).

    Если текст после повторного OCR всё ещё нечитаем — LLM НЕ вызывается вообще (см.
    докстринг llm_cleanup.py: LLM применяется только к тексту, уже прошедшему этот гейт).
    """
    engine = get_ocr_engine()
    if engine is None:
        logger.warning("Retry OCR: нет доступного движка (paddle/tesseract/yandex)")
        return "", True

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page_count = doc.page_count
        pages: list[str] = []
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            pages.append(engine.image_to_text(pix.tobytes("jpeg")) or "")
    finally:
        doc.close()

    raw_text = strip_signature_block(reflow_soft_linebreaks("\n\n".join(pages)))
    if is_text_unreadable(raw_text, page_count):
        return raw_text, True

    cleaned_pages = [clean_page_with_safety_net(page_text) for page_text in pages]
    cleaned_text = strip_signature_block(reflow_soft_linebreaks("\n\n".join(cleaned_pages)))
    return cleaned_text, False

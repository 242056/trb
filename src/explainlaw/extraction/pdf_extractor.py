import logging
from dataclasses import dataclass

import fitz

from explainlaw.config import settings
from explainlaw.db.models import TextExtractionMethod
from explainlaw.extraction.ocr_engines import get_ocr_engine

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    text: str
    method: TextExtractionMethod
    page_count: int


def _normalize_text(text: str) -> str:
    from explainlaw.gates.text_checks import reflow_soft_linebreaks, strip_signature_block

    # PDF/OCR часто даёт soft-wrap по словам («Сторонами\\nконцессионного»).
    text = reflow_soft_linebreaks(text)
    # Служебный блок подписи/канцелярии в конце закона — не текст закона.
    return strip_signature_block(text)


def extract_text_from_pdf(pdf_bytes: bytes) -> ExtractionResult:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        pages = [page.get_text("text") for page in doc]
        text = _normalize_text("\n".join(pages))
        if len(text) >= settings.ocr_text_threshold:
            return ExtractionResult(
                text=text, method=TextExtractionMethod.pdf_text, page_count=len(pages)
            )

        if not settings.ocr_enabled:
            logger.debug("OCR отключён (OCR_ENABLED=false)")
            return ExtractionResult(
                text=text, method=TextExtractionMethod.pdf_text, page_count=len(pages)
            )

        # tesseract: сначала PyMuPDF OCR (тот же tess, быстрее), затем pytesseract-профиль.
        preferred = (settings.ocr_engine or "tesseract").strip().lower()
        if preferred == "tesseract":
            ocr_text = _ocr_with_fitz(doc)
            if not ocr_text or len(ocr_text) < settings.ocr_text_threshold:
                ocr_text = _ocr_pdf_pages(doc)
        else:
            ocr_text = _ocr_pdf_pages(doc)
            if not ocr_text or len(ocr_text) < settings.ocr_text_threshold:
                ocr_text = _ocr_with_fitz(doc)

        if ocr_text and len(ocr_text) > len(text):
            return ExtractionResult(
                text=ocr_text, method=TextExtractionMethod.ocr, page_count=len(pages)
            )
        return ExtractionResult(
            text=text, method=TextExtractionMethod.pdf_text, page_count=len(pages)
        )
    finally:
        doc.close()


def _ocr_pdf_pages(doc: fitz.Document) -> str | None:
    engine = get_ocr_engine()
    if engine is None:
        logger.warning("Нет доступного OCR-движка (paddle/tesseract/yandex)")
        return None
    chunks: list[str] = []
    try:
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            chunks.append(engine.image_to_text(pix.tobytes("jpeg")))
        return _normalize_text("\n\n".join(chunks))
    except Exception:
        logger.exception("OCR (%s) не удался", engine.name)
        return None


def _ocr_with_fitz(doc: fitz.Document) -> str | None:
    try:
        chunks: list[str] = []
        for page in doc:
            textpage = page.get_textpage_ocr(language="rus", dpi=200, full=True)
            chunks.append(page.get_text(textpage=textpage))
        return _normalize_text("\n".join(chunks))
    except Exception:
        logger.debug("PyMuPDF OCR недоступен", exc_info=True)
        return None

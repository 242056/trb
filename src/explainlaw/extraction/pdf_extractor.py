import logging
import re
from dataclasses import dataclass

import fitz

from explainlaw.config import settings
from explainlaw.db.models import TextExtractionMethod

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    text: str
    method: TextExtractionMethod
    page_count: int


def _normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_text_from_pdf(pdf_bytes: bytes) -> ExtractionResult:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        pages = [page.get_text("text") for page in doc]
        text = _normalize_text("\n".join(pages))
        if len(text) >= settings.ocr_text_threshold:
            return ExtractionResult(text=text, method=TextExtractionMethod.pdf_text, page_count=len(pages))

        if not settings.ocr_enabled:
            logger.debug("OCR отключён (OCR_ENABLED=false), используем извлечённый текст PDF")
            return ExtractionResult(text=text, method=TextExtractionMethod.pdf_text, page_count=len(pages))

        ocr_text = _ocr_with_fitz(doc)
        if not ocr_text or len(ocr_text) < settings.ocr_text_threshold:
            ocr_text = _ocr_fallback(pdf_bytes)

        if ocr_text and len(ocr_text) > len(text):
            return ExtractionResult(
                text=ocr_text, method=TextExtractionMethod.ocr, page_count=len(pages)
            )
        return ExtractionResult(text=text, method=TextExtractionMethod.pdf_text, page_count=len(pages))
    finally:
        doc.close()


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


def _ocr_fallback(pdf_bytes: bytes) -> str | None:
    try:
        from pdf2image import convert_from_bytes
        import pytesseract
    except ImportError:
        logger.debug("OCR-зависимости не установлены (pip install explainlaw[ocr])")
        return None

    try:
        images = convert_from_bytes(pdf_bytes, dpi=200)
        chunks = [pytesseract.image_to_string(img, lang="rus") for img in images]
        return _normalize_text("\n\n".join(chunks))
    except Exception:
        logger.exception("OCR не удался")
        return None

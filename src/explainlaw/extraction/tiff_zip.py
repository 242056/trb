"""Конвертация ZIP со страницами TIFF (старый формат pravo.gov.ru) в PDF."""

from __future__ import annotations

import io
import logging
import zipfile

import fitz
from PIL import Image

logger = logging.getLogger(__name__)

_IMAGE_SUFFIXES = (".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp")
_MAX_WIDTH = 1600
_JPEG_QUALITY = 80


def tiff_zip_to_pdf(zip_bytes: bytes) -> bytes:
    """Собирает компактный многостраничный PDF из изображений внутри ZIP."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = sorted(
            n
            for n in zf.namelist()
            if not n.endswith("/") and n.lower().endswith(_IMAGE_SUFFIXES)
        )
        if not names:
            raise ValueError("ZIP не содержит изображений страниц")

        doc = fitz.open()
        try:
            for name in names:
                raw = zf.read(name)
                img = Image.open(io.BytesIO(raw))
                if img.mode != "RGB":
                    img = img.convert("RGB")

                if img.width > _MAX_WIDTH:
                    ratio = _MAX_WIDTH / img.width
                    img = img.resize(
                        (_MAX_WIDTH, max(1, int(img.height * ratio))),
                        Image.Resampling.LANCZOS,
                    )

                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
                jpeg = buf.getvalue()

                page_w, page_h = 595, 842
                page = doc.new_page(width=page_w, height=page_h)
                scale = min((page_w - 40) / img.width, (page_h - 40) / img.height)
                w, h = img.width * scale, img.height * scale
                x0 = (page_w - w) / 2
                y0 = (page_h - h) / 2
                page.insert_image(fitz.Rect(x0, y0, x0 + w, y0 + h), stream=jpeg)

            pdf_bytes = doc.tobytes(deflate=True, garbage=3)
            logger.info(
                "TIFF-ZIP→PDF: %d стр., %d → %d байт",
                len(names),
                len(zip_bytes),
                len(pdf_bytes),
            )
            return pdf_bytes
        finally:
            doc.close()

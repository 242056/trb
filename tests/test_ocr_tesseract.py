"""Smoke: tesseract-профиль + постпроцессинг на реальном скане pravo."""

from __future__ import annotations

import io
from pathlib import Path

import fitz
import pytest
from PIL import Image

from explainlaw.extraction.ocr_engines import TesseractEngine
from explainlaw.gates.text_checks import fix_ocr_artifacts, reflow_soft_linebreaks

_SAMPLE = Path("/tmp/ocr_research/0001202608040003.pdf")


@pytest.mark.skipif(not _SAMPLE.is_file(), reason="research sample PDF not present")
def test_tesseract_plus_postprocess_cleans_superscripts_on_scan():
    engine = TesseractEngine()
    assert engine.available()

    doc = fitz.open(_SAMPLE)
    try:
        # стр. 1–3: заголовок + тело с 84¹ / 15¹ / 39⁷
        chunks: list[str] = []
        for page in list(doc)[:3]:
            pix = page.get_pixmap(dpi=200)
            chunks.append(engine.image_to_text(pix.tobytes("png")))
        raw = "\n\n".join(chunks)
    finally:
        doc.close()

    assert len(raw) > 500
    cleaned = reflow_soft_linebreaks(raw)
    # после постпроцессинга не должно остаться типичного мусора superscripts
    assert "84?" not in cleaned
    assert "15'" not in cleaned
    assert "39°" not in cleaned
    assert "Федеральный" in cleaned or "ФЕДЕРАЛЬНЫЙ" in cleaned.upper()


def test_tesseract_engine_accepts_png_bytes():
    engine = TesseractEngine()
    if not engine.available():
        pytest.skip("pytesseract not installed")
    # минимальный белый PNG — просто проверяем, что пайплайн не падает
    img = Image.new("RGB", (200, 60), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    text = engine.image_to_text(buf.getvalue())
    assert isinstance(text, str)


def test_fix_ocr_artifacts_idempotent_on_clean_text():
    clean = "статья 84 Федерального закона часть 15 настоящего"
    assert fix_ocr_artifacts(clean) == clean

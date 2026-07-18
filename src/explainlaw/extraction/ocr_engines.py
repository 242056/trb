"""OCR backends для сканов (§3.4).

Публичного drop-in «SberOCR API» нет. Варианты:
- paddle — обычно лучше Tesseract на русском печатном
- tesseract — fallback
- yandex — Yandex Vision OCR
"""

from __future__ import annotations

import base64
import logging
from typing import Protocol

import httpx

from explainlaw.config import settings

logger = logging.getLogger(__name__)


class OcrEngine(Protocol):
    name: str

    def available(self) -> bool: ...

    def image_to_text(self, image_bytes: bytes) -> str: ...


class TesseractEngine:
    name = "tesseract"

    def available(self) -> bool:
        try:
            import pytesseract  # noqa: F401

            return True
        except ImportError:
            return False

    def image_to_text(self, image_bytes: bytes) -> str:
        import io

        import pytesseract
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes))
        return pytesseract.image_to_string(img, lang="rus")


class PaddleEngine:
    name = "paddle"
    _reader = None

    def available(self) -> bool:
        try:
            import paddleocr  # noqa: F401

            return True
        except ImportError:
            return False

    def _get_reader(self):
        if self._reader is None:
            from paddleocr import PaddleOCR

            self._reader = PaddleOCR(use_angle_cls=True, lang="ru", show_log=False)
        return self._reader

    def image_to_text(self, image_bytes: bytes) -> str:
        import io

        import numpy as np
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        arr = np.array(img)
        result = self._get_reader().ocr(arr, cls=True)
        lines: list[str] = []
        if not result:
            return ""
        for block in result:
            if not block:
                continue
            for item in block:
                if item and len(item) >= 2 and item[1]:
                    lines.append(str(item[1][0]))
        return "\n".join(lines)


class YandexVisionEngine:
    name = "yandex"

    def available(self) -> bool:
        return bool(settings.yandex_vision_api_key or settings.yandex_vision_iam_token)

    def image_to_text(self, image_bytes: bytes) -> str:
        headers = {"Content-Type": "application/json"}
        if settings.yandex_vision_iam_token:
            headers["Authorization"] = f"Bearer {settings.yandex_vision_iam_token}"
        else:
            headers["Authorization"] = f"Api-Key {settings.yandex_vision_api_key}"

        payload = {
            "mimeType": "JPEG",
            "languageCodes": ["ru", "en"],
            "model": "page",
            "content": base64.b64encode(image_bytes).decode("ascii"),
        }
        url = "https://ocr.api.cloud.yandex.net/ocr/v1/recognizeText"
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        result = data.get("result") or data
        ann = result.get("textAnnotation") or {}
        return (ann.get("fullText") or "").strip()


def get_ocr_engine() -> OcrEngine | None:
    preferred = (settings.ocr_engine or "tesseract").strip().lower()
    if preferred == "paddle":
        engines: list[OcrEngine] = [PaddleEngine(), TesseractEngine(), YandexVisionEngine()]
    elif preferred == "yandex":
        engines = [YandexVisionEngine(), PaddleEngine(), TesseractEngine()]
    else:
        engines = [TesseractEngine(), PaddleEngine(), YandexVisionEngine()]

    for eng in engines:
        if eng.available():
            logger.info("OCR engine: %s", eng.name)
            return eng
    return None

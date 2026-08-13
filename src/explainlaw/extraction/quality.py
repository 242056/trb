"""Гейт «текст документа нечитаем» — весь документ целиком, не постранично.

Осознанное ограничение (по прямому решению пользователя): гейт не поймает документ, который
в среднем читается нормально, но содержит один нечитаемый/сфабрикованный LLM фрагмент внутри
(см. scripts/ocr_benchmark/README.md, случай 0001201602150045) — постраничная детекция
намеренно не реализована.
"""

from __future__ import annotations

from explainlaw.config import settings
from explainlaw.gates.text_checks import garbage_char_ratio


def is_text_unreadable(text: str, page_count: int) -> bool:
    stripped = (text or "").strip()
    if garbage_char_ratio(stripped) > settings.ocr_garbage_ratio_threshold:
        return True
    return len(stripped) < settings.ocr_min_chars_per_page * max(page_count, 1)

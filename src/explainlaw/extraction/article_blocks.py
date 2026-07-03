"""Разбиение текста поправки на статьи для поузловой обработки."""

from __future__ import annotations

import re

_ARTICLE_RE = re.compile(
    r"Статья\s+(\d+(?:\.\d+)?)\s*(.*?)(?=Статья\s+\d+(?:\.\d+)?\s|$)",
    re.IGNORECASE | re.DOTALL,
)


def split_article_blocks(full_text: str) -> list[tuple[str, str]]:
    """Возвращает пары (номер_статьи, тело_статьи)."""
    text = full_text.strip()
    blocks = [(m.group(1), m.group(2).strip()) for m in _ARTICLE_RE.finditer(text)]
    if blocks:
        return blocks
    return [("1", text)]

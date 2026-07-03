"""Извлечение текста статьи из полного текста акта."""

from __future__ import annotations

import re


def extract_article_text(full_text: str, article: str) -> str | None:
    """Возвращает текст статьи N из полного текста акта."""
    pattern = re.compile(
        rf"Статья\s+{re.escape(article)}\.?\s*(.*?)(?=Статья\s+\d+(?:\.\d+)?\s|$)",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(full_text)
    if not match:
        return None
    text = match.group(1).strip()
    return text if len(text) > 20 else None

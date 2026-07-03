import re

# Фрагмент для сводки: преамбула + первые статьи (не весь документ)
_FRAGMENT_LIMIT = 4000

_PREAMBLE_RE = re.compile(
    r"(Статья\s+1\.?.*)",
    re.IGNORECASE | re.DOTALL,
)


def extract_summary_fragment(full_text: str) -> str:
    """Вырезает релевантный фрагмент для сводки (узел между текстом и ИИ)."""
    text = full_text.strip()
    if len(text) <= _FRAGMENT_LIMIT:
        return text

    match = _PREAMBLE_RE.search(text)
    if match:
        start = max(0, match.start() - 500)
        fragment = text[start : start + _FRAGMENT_LIMIT]
        return fragment.strip()

    return text[:_FRAGMENT_LIMIT].strip()

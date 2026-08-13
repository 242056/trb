"""Извлечение и сравнение «критичных элементов» текста НПА (числа/даты/ссылки на статьи/суммы).

Самостоятельные регэкспы — НЕ переиспользуют приватные `_SUMMARY_*`/`_FZ_NUMBER_RE` из
`gates/text_checks.py`: та семантика заточена под другую задачу (не соврала ли LLM-сводка
число, отсутствующее в источнике человека-документа), а здесь нужно извлечь все юридически
значимые числа/даты/ссылки из самого текста закона для дословного сравнения OCR до/после
LLM-правки (см. extraction/llm_cleanup.py) или OCR vs эталон (см. scripts/ocr_benchmark).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)

_ARTICLE_POINT_RE = re.compile(
    r"(?:стать[яию]|част[ьи]|пункт[а-я]*|подпункт[а-я]*)\s+\d+(?:\.\d+)?(?:-\d+)?",
    re.IGNORECASE,
)
_DATE_DOT_RE = re.compile(r"\d{1,2}\.\d{1,2}\.\d{4}")
_DATE_ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DATE_RU_RE = re.compile(rf"\d{{1,2}}\s+(?:{'|'.join(_MONTHS)})\s+\d{{4}}\s*год[а]?", re.IGNORECASE)
_SUM_MONEY_RE = re.compile(
    r"[\d\s]+(?:,\d+)?\s*(?:руб(?:лей|ля|\.)?|коп(?:еек|ейки|\.)?)",
    re.IGNORECASE,
)
_DEADLINE_RE = re.compile(
    r"(?:не позднее|в течение|до)\s+\d+\s+(?:дн(?:я|ей)|месяц\w*|лет|год\w*)",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"\d+(?:[.,]\d+)?\s*%")
_PLAIN_NUMBER_RE = re.compile(r"\d{2,}")

# Порядок важен: более специфичные категории вычищаются из текста первыми, чтобы
# plain_number не задублировал числа, уже пойманные датами/суммами/сроками/%.
_CATEGORY_PATTERNS = (
    ("article_point_ref", _ARTICLE_POINT_RE),
    ("date_dot", _DATE_DOT_RE),
    ("date_iso", _DATE_ISO_RE),
    ("date_ru", _DATE_RU_RE),
    ("sum_money", _SUM_MONEY_RE),
    ("deadline", _DEADLINE_RE),
    ("percent", _PERCENT_RE),
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


@dataclass
class CriticalElements:
    by_category: dict[str, list[str]] = field(default_factory=dict)

    def all_items(self) -> list[tuple[str, str]]:
        return [(cat, item) for cat, items in self.by_category.items() for item in items]

    @property
    def total(self) -> int:
        return len(self.all_items())


def extract_critical_elements(text: str) -> CriticalElements:
    """Извлекает по категориям; вычищает найденные спаны, чтобы plain_number не дублировал."""
    remaining = text or ""
    by_category: dict[str, list[str]] = {}

    for name, pattern in _CATEGORY_PATTERNS:
        found: list[str] = []
        spans: list[tuple[int, int]] = []
        for match in pattern.finditer(remaining):
            found.append(_normalize(match.group(0)))
            spans.append(match.span())
        by_category[name] = found
        # маскируем найденные спаны пробелами той же длины, не сдвигая индексы остальных regex
        if spans:
            chars = list(remaining)
            for start, end in spans:
                for i in range(start, end):
                    chars[i] = " "
            remaining = "".join(chars)

    plain_numbers = [_normalize(m.group(0)) for m in _PLAIN_NUMBER_RE.finditer(remaining)]
    by_category["plain_number"] = plain_numbers

    return CriticalElements(by_category=by_category)


@dataclass
class CriticalElementsComparison:
    total: int
    matched: int
    missing: list[tuple[str, str]]

    @property
    def accuracy(self) -> float:
        return self.matched / self.total if self.total else 1.0


def compare_critical_elements(source_text: str, candidate_text: str) -> CriticalElementsComparison:
    """Дословное присутствие каждого критичного элемента эталона в тексте кандидата (OCR)."""
    source_elements = extract_critical_elements(source_text)
    candidate_normalized = _normalize(candidate_text)

    matched = 0
    missing: list[tuple[str, str]] = []
    for category, item in source_elements.all_items():
        if item and item in candidate_normalized:
            matched += 1
        else:
            missing.append((category, item))

    return CriticalElementsComparison(total=source_elements.total, matched=matched, missing=missing)

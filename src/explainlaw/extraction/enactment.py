import re
from dataclasses import dataclass
from datetime import date

_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


@dataclass
class EnactmentMatch:
    effective_date: date
    unit_address: dict
    conditions: str | None
    text_fragment: str | None


_DATE_RE = re.compile(
    r"(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(\d{4})",
    re.IGNORECASE,
)

_ARTICLE_DATE_RE = re.compile(
    r"Статья\s+(\d+(?:\.\d+)?)\s+.*?вступает\s+в\s+силу\s+(\d{1,2})\s+"
    r"(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(\d{4})",
    re.IGNORECASE | re.DOTALL,
)

_PUBLICATION_EFFECTIVE_RE = re.compile(
    r"со\s+дня\s+(?:его\s+|их\s+)?(?:официального\s+)?опубликования",
    re.IGNORECASE,
)


def mentions_publication_effective(text: str) -> bool:
    """«вступает в силу со дня (официального) опубликования» — без явной даты."""
    return bool(_PUBLICATION_EFFECTIVE_RE.search(text or ""))


def _parse_ru_date(day: str, month_name: str, year: str) -> date | None:
    """OCR часто даёт «31 февраля» — пропускаем, не валим документ."""
    try:
        month = _MONTHS[month_name.lower()]
        return date(int(year), month, int(day))
    except (KeyError, ValueError, TypeError):
        return None


def extract_enactments(text: str) -> list[EnactmentMatch]:
    results: list[EnactmentMatch] = []
    seen: set[tuple[date, str]] = set()

    for match in _ARTICLE_DATE_RE.finditer(text):
        article = match.group(1)
        eff = _parse_ru_date(match.group(2), match.group(3), match.group(4))
        if eff is None:
            continue
        key = (eff, article)
        if key in seen:
            continue
        seen.add(key)
        results.append(
            EnactmentMatch(
                effective_date=eff,
                unit_address={"статья": article},
                conditions=None,
                text_fragment=match.group(0)[:500],
            )
        )

    if not results:
        for match in _DATE_RE.finditer(text):
            eff = _parse_ru_date(match.group(1), match.group(2), match.group(3))
            if eff is None or (eff, "document") in seen:
                continue
            seen.add((eff, "document"))
            start = max(0, match.start() - 120)
            fragment = text[start : match.end() + 80]
            if "вступает в силу" in fragment.lower():
                results.append(
                    EnactmentMatch(
                        effective_date=eff,
                        unit_address={},
                        conditions=None,
                        text_fragment=fragment.strip(),
                    )
                )

    return results

"""Распознавание и сопоставление идентификаторов актов (номер + дата + название)."""

from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from explainlaw.db.models import NpaDocument

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

# Федеральный закон от 21 июля 1997 года №114-ФЗ «…»
_FZ_FULL_RE = re.compile(
    r"Федеральн(?:ый|ого|ому|ым)\s+закон(?:а|у|ом)?\s+"
    r"(?:от\s+(\d{1,2})\s+(" + "|".join(_MONTHS) + r")\s+(\d{4})\s+года?\s*)?"
    r"(?:№\s*([\d]+(?:-[\wА-Яа-я]+)?)\s*)?"
    r"[«\"]([^»\"]+)[»\"]",
    re.IGNORECASE,
)

# Федеральный закон «…» (в редакции Федерального закона от … №…-ФЗ)
_FZ_TITLE_FIRST_RE = re.compile(
    r"Федеральн(?:ый|ого|ому|ым)\s+закон(?:а|у|ом)?\s+"
    r"[«\"]([^»\"]+)[»\"]"
    r"(?:\s*\([^)]*?от\s+(\d{1,2})\s+(" + "|".join(_MONTHS) + r")\s+(\d{4})\s+года?\s*"
    r"№\s*([\d]+(?:-[\wА-Яа-я]+)?)[^)]*\))?",
    re.IGNORECASE,
)

# Короткая форма: от 12.03.2001
_FZ_DOT_DATE_RE = re.compile(
    r"Федеральн(?:ый|ого|ому|ым)\s+закон(?:а|у|ом)?\s+"
    r"[«\"]([^»\"]+)[»\"]"
    r"(?:\s+от\s+(\d{1,2})\.(\d{1,2})\.(\d{4}))?",
    re.IGNORECASE,
)


def _parse_ru_date(day: str, month_name: str, year: str) -> str:
    month = _MONTHS[month_name.lower()]
    return date(int(year), month, int(day)).isoformat()


def _normalize_number(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = raw.strip().upper().replace(" ", "")
    if not cleaned.endswith("-ФЗ") and cleaned.isdigit():
        return f"{cleaned}-ФЗ"
    return cleaned


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def parse_federal_law_references(text: str) -> list[dict[str, Any]]:
    """Извлекает идентификаторы ФЗ из текста. Порядок — по появлению."""
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(identifier: dict[str, Any]) -> None:
        key = identifier_key(identifier)
        if key in seen:
            return
        seen.add(key)
        results.append(identifier)

    for match in _FZ_FULL_RE.finditer(text):
        identifier: dict[str, Any] = {
            "type": "federal_law",
            "name": match.group(5).strip(),
        }
        if match.group(1) and match.group(2) and match.group(3):
            identifier["date"] = _parse_ru_date(match.group(1), match.group(2), match.group(3))
        number = _normalize_number(match.group(4))
        if number:
            identifier["number"] = number
        if not identifier.get("number") and not identifier.get("date"):
            continue
        add(identifier)

    for match in _FZ_TITLE_FIRST_RE.finditer(text):
        identifier = {
            "type": "federal_law",
            "name": match.group(1).strip(),
        }
        if match.group(2) and match.group(3) and match.group(4):
            identifier["date"] = _parse_ru_date(match.group(2), match.group(3), match.group(4))
        number = _normalize_number(match.group(5) if match.lastindex and match.lastindex >= 5 else None)
        if number:
            identifier["number"] = number
        add(identifier)

    for match in _FZ_DOT_DATE_RE.finditer(text):
        identifier = {
            "type": "federal_law",
            "name": match.group(1).strip(),
        }
        if match.group(2):
            identifier["date"] = (
                f"{match.group(4)}-{int(match.group(3)):02d}-{int(match.group(2)):02d}"
            )
        if not identifier.get("date"):
            continue
        add(identifier)

    return results


def identifier_key(identifier: dict[str, Any]) -> str:
    """Стабильный ключ для дедупликации и очереди."""
    parts = [
        identifier.get("type", "unknown"),
        identifier.get("number") or "",
        identifier.get("date") or "",
        _normalize_name(identifier.get("name", "")),
    ]
    raw = "|".join(parts)
    if len(raw) <= 200:
        return raw
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def find_document_by_identifier(
    session: Session, identifier: dict[str, Any]
) -> NpaDocument | None:
    """Ищет документ в базе по номеру+дате, затем по номеру, затем по названию."""
    if identifier.get("eo_number"):
        doc = session.execute(
            select(NpaDocument).where(NpaDocument.eo_number == identifier["eo_number"])
        ).scalar_one_or_none()
        if doc:
            return doc

    number = identifier.get("number")
    act_date = identifier.get("date")
    parsed_date = date.fromisoformat(act_date) if act_date else None

    if number and parsed_date:
        doc = session.execute(
            select(NpaDocument)
            .where(
                NpaDocument.number == number,
                NpaDocument.document_date == parsed_date,
            )
            .order_by(NpaDocument.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if doc:
            return doc

    if number:
        # Один номер может встречаться у нескольких записей (дубликаты/разные даты) — берём последний по дате
        doc = session.execute(
            select(NpaDocument)
            .where(NpaDocument.number == number)
            .order_by(NpaDocument.document_date.desc().nullslast(), NpaDocument.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if doc:
            return doc

    name = identifier.get("name")
    if not name:
        return None

    norm_name = _normalize_name(name)
    candidates = session.execute(
        select(NpaDocument).where(
            or_(
                NpaDocument.name.ilike(f"%{name[:40]}%"),
                NpaDocument.complex_name.ilike(f"%{name[:40]}%"),
            )
        )
    ).scalars().all()

    if parsed_date:
        for doc in candidates:
            if doc.document_date == parsed_date:
                return doc

    if len(candidates) == 1:
        return candidates[0]

    for doc in candidates:
        if doc.name and _normalize_name(doc.name) == norm_name:
            return doc

    return None

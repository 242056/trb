"""Разметка отраслей ФЗ (§4.3, §5.5)."""

from __future__ import annotations


from sqlalchemy import select
from sqlalchemy.orm import Session

from explainlaw.db.models import NpaDocument, NpaSector, SectorDict

# code -> (keywords, display name)
SECTOR_CATALOG: dict[str, tuple[tuple[str, ...], str]] = {
    "tax": (("налог", "ндс", "ндфл", "налоговый кодекс"), "Налоги"),
    "labor": (("труд", "занятост", "профсоюз", "заработн"), "Труд"),
    "criminal": (("уголовн", "ук рф", "уголовного кодекса"), "Уголовное право"),
    "civil": (("гражданск", "гк рф", "гражданского кодекса"), "Гражданское право"),
    "admin": (("административн", "коап", "административного"), "Административное право"),
    "budget": (("бюджет", "финанс", "казначей"), "Бюджет и финансы"),
    "health": (("здравоохран", "медицин", "фармацевт"), "Здравоохранение"),
    "education": (("образован", "наук", "университет"), "Образование"),
    "transport": (("транспорт", "автомобил", "железнодорож", "авиа"), "Транспорт"),
    "housing": (("жилищ", "земел", "недвижим"), "Жилище и земля"),
    "digital": (("информац", "связ", "интернет", "персональн", "данн"), "IT и связь"),
    "business": (("предприним", "конкуренц", "лицензир", "регулирован"), "Бизнес"),
}


def ensure_sector_dict(session: Session) -> None:
    for code, (_, name) in SECTOR_CATALOG.items():
        if session.get(SectorDict, code) is None:
            session.add(SectorDict(code=code, name=name))
    session.flush()


def _score_text(text: str) -> list[tuple[str, float]]:
    lowered = text.lower()
    scores: list[tuple[str, float]] = []
    for code, (keywords, _) in SECTOR_CATALOG.items():
        hits = sum(1 for kw in keywords if kw in lowered)
        if hits:
            scores.append((code, min(1.0, 0.35 + hits * 0.2)))
    scores.sort(key=lambda item: item[1], reverse=True)
    return scores[:3]


def assign_sectors(session: Session, doc: NpaDocument, *, text: str) -> int:
    """Присваивает до 3 отраслей документу. Возвращает число новых привязок."""
    ensure_sector_dict(session)
    existing = {
        row.sector_code
        for row in session.execute(
            select(NpaSector).where(NpaSector.document_id == doc.id)
        ).scalars()
    }
    corpus = " ".join(filter(None, [doc.name, doc.complex_name, text[:4000]]))
    added = 0
    for code, confidence in _score_text(corpus):
        if code in existing:
            continue
        session.add(
            NpaSector(document_id=doc.id, sector_code=code, confidence=confidence)
        )
        added += 1
    return added

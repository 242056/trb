"""Помещение прошедших гейты карточек в банк готовых (§9.3, итерация 4)."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from explainlaw.db.models import NpaDelta, NpaDocument, NpaSummary, PostBank, PostItem, PostStatus, PostType
from explainlaw.extraction.enactment import mentions_publication_effective
from explainlaw.gates.text_checks import reflow_soft_linebreaks

_SEE_SOURCE = "см. первоисточник"
_MAX_CHANGES_IN_LINE = 3


def _short_title(name: str | None) -> str:
    if not name:
        return "Федеральный закон"
    return re.sub(r"\s+", " ", name.strip().strip('"«»'))


def card_title(doc: NpaDocument, summary: NpaSummary) -> str:
    """Короткий заголовок карточки: приоритет — цепляющий заголовок от Gateway."""
    title = (summary.title or "").strip()
    return title if title else _short_title(doc.name)


def _enactment_line(doc: NpaDocument) -> str:
    dates = sorted({e.effective_date for e in (doc.enactments or [])})
    if len(dates) == 1:
        return dates[0].strftime("%d.%m.%Y")
    if len(dates) > 1:
        return "поэтапно, см. закон"
    full_text = doc.text.full_text if doc.text else ""
    if mentions_publication_effective(full_text or ""):
        return "со дня опубликования"
    return _SEE_SOURCE


def _changes_line(delta: NpaDelta) -> str:
    changes = delta.delta_data.get("changes") or []
    seen: set[tuple[str, str | None]] = set()
    entries: list[str] = []
    for change in changes:
        target = change.get("target_act") or {}
        act_label = target.get("number") or target.get("name")
        if not act_label:
            continue
        article = (change.get("unit_address") or {}).get("статья")
        key = (act_label, article)
        if key in seen:
            continue
        seen.add(key)
        entries.append(f"{act_label}, ст. {article}" if article else act_label)
        if len(entries) >= _MAX_CHANGES_IN_LINE:
            break
    return "; ".join(entries) if entries else "—"


def format_card_content(doc: NpaDocument, summary: NpaSummary, delta: NpaDelta) -> str:
    document_date = doc.document_date.strftime("%d.%m.%Y") if doc.document_date else _SEE_SOURCE
    publish_date = doc.publish_date_short.strftime("%d.%m.%Y") if doc.publish_date_short else _SEE_SOURCE

    lines = [
        f"Принят: {document_date}",
        f"Опубликован: {publish_date}",
        f"Вступает в силу: {_enactment_line(doc)}",
        "",
        reflow_soft_linebreaks(summary.summary_text.strip()),
        "",
        f"Меняет: {_changes_line(delta)}",
    ]
    if doc.source_url:
        lines.append(f"Источник: {doc.source_url}")
    return "\n".join(lines)


def promote_to_post_bank(
    session: Session,
    *,
    doc: NpaDocument,
    summary: NpaSummary,
    delta: NpaDelta,
) -> tuple[int | None, bool]:
    """Создаёт карточку в post_bank, если её ещё нет. Возвращает (post_id, created)."""
    existing_item = session.execute(
        select(PostItem)
        .join(PostBank, PostBank.id == PostItem.post_id)
        .where(
            PostItem.document_id == doc.id,
            PostBank.post_type == PostType.single,
        )
        .limit(1)
    ).scalar_one_or_none()
    if existing_item:
        return existing_item.post_id, False

    number = doc.number or "—"
    post = PostBank(
        title=f"№{number} — {card_title(doc, summary)}",
        content=format_card_content(doc, summary, delta),
        post_type=PostType.single,
        status=PostStatus.ready,
    )
    session.add(post)
    session.flush()
    session.add(PostItem(post_id=post.id, document_id=doc.id, order_index=0))
    return post.id, True

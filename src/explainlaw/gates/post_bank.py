"""Помещение прошедших гейты карточек в банк готовых (§9.3, итерация 4)."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from explainlaw.db.models import NpaDelta, NpaDocument, NpaSummary, PostBank, PostItem, PostStatus, PostType
from explainlaw.extraction.act_identifier import parse_federal_law_references
from explainlaw.extraction.enactment import mentions_publication_effective
from explainlaw.gates.text_checks import first_n_sentences, reflow_soft_linebreaks, sanitize_article_number

_SEE_SOURCE = "см. первоисточник"
_MAX_CHANGES_IN_LINE = 3
_ARTICLE_IN_NAME_RE = re.compile(
    r"стать(?:ю|и|е|я)\s+(\d+(?:\.\d+)?(?:-\d+)?)",
    re.IGNORECASE,
)
_CODE_ALIASES = (
    (re.compile(r"кодекс\w*\s+российской федерации об административных правонарушениях|коап", re.I), "КоАП РФ"),
    (re.compile(r"трудов\w*\s+кодекс", re.I), "Трудовой кодекс РФ"),
    (re.compile(r"жилищн\w*\s+кодекс", re.I), "Жилищный кодекс РФ"),
    (re.compile(r"гражданск\w*\s+кодекс", re.I), "Гражданский кодекс РФ"),
    (re.compile(r"налогов\w*\s+кодекс", re.I), "Налоговый кодекс РФ"),
    (re.compile(r"семей\w*\s+кодекс", re.I), "Семейный кодекс РФ"),
    (re.compile(r"уголовн\w*\s+кодекс", re.I), "Уголовный кодекс РФ"),
)


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


def _short_act_label(name: str | None, number: str | None = None) -> str:
    raw = re.sub(r"\s+", " ", (name or "").strip().strip('"«»'))
    for pattern, alias in _CODE_ALIASES:
        if pattern.search(raw):
            return alias
    if raw:
        return raw[:80].rstrip(" ,;")
    return number or "—"


def _articles_from_name(name: str | None) -> list[str]:
    found: list[str] = []
    for match in _ARTICLE_IN_NAME_RE.finditer(name or ""):
        article = sanitize_article_number(match.group(1))
        if article and article not in found:
            found.append(article)
    return found


def _changes_line(doc: NpaDocument, delta: NpaDelta) -> str:
    changes = delta.delta_data.get("changes") or []
    seen: set[tuple[str, str | None]] = set()
    entries: list[str] = []

    def add(label: str, article: str | None) -> None:
        key = (label, article)
        if key in seen or not label:
            return
        seen.add(key)
        entries.append(f"{label}, ст. {article}" if article else label)

    for change in changes:
        target = change.get("target_act") or {}
        label = _short_act_label(target.get("name"), target.get("number"))
        if label == "—":
            continue
        article = sanitize_article_number((change.get("unit_address") or {}).get("статья"))
        add(label, article)
        if len(entries) >= _MAX_CHANGES_IN_LINE:
            return "; ".join(entries)

    if not entries:
        refs = parse_federal_law_references(doc.name or "")
        articles = _articles_from_name(doc.name)
        if refs:
            label = _short_act_label(refs[0].get("name"), refs[0].get("number"))
            if articles:
                for article in articles[:_MAX_CHANGES_IN_LINE]:
                    add(label, article)
            else:
                add(label, None)
        elif articles:
            label = _short_act_label(doc.name)
            add(label, articles[0])

    return "; ".join(entries) if entries else "—"


def format_card_content(doc: NpaDocument, summary: NpaSummary, delta: NpaDelta) -> str:
    document_date = doc.document_date.strftime("%d.%m.%Y") if doc.document_date else _SEE_SOURCE
    publish_date = doc.publish_date_short.strftime("%d.%m.%Y") if doc.publish_date_short else _SEE_SOURCE

    lines = [
        f"Принят: {document_date}",
        f"Опубликован: {publish_date}",
        f"Вступает в силу: {_enactment_line(doc)}",
        "",
        first_n_sentences(reflow_soft_linebreaks(summary.summary_text.strip()), 2),
        "",
        f"Меняет: {_changes_line(doc, delta)}",
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
    number = doc.number or "—"
    title = f"№{number} — {card_title(doc, summary)}"
    content = format_card_content(doc, summary, delta)
    if existing_item:
        post = session.get(PostBank, existing_item.post_id)
        if post is not None:
            post.title = title
            post.content = content
        return existing_item.post_id, False

    post = PostBank(
        title=title,
        content=content,
        post_type=PostType.single,
        status=PostStatus.ready,
    )
    session.add(post)
    session.flush()
    session.add(PostItem(post_id=post.id, document_id=doc.id, order_index=0))
    return post.id, True

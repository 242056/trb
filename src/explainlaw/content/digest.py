"""Сборка дайджеста и запасных форматов (§7.2)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from explainlaw.content.scoring import ScoredCard
from explainlaw.db.models import NpaDocument, NpaEnactment, PostBank, PostItem, PostStatus, PostType


def _current_week_bounds(today: date) -> tuple[date, date]:
    """Текущая календарная неделя (пн–вс), для «вступает в силу»."""
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    return start, end


def _past_week_bounds(today: date) -> tuple[date, date]:
    """Прошедшая календарная неделя (пн–вс до текущего понедельника)."""
    this_monday = today - timedelta(days=today.weekday())
    start = this_monday - timedelta(days=7)
    end = this_monday - timedelta(days=1)
    return start, end


def build_digest_content(cards: list[ScoredCard], *, week_label: str) -> str:
    from explainlaw.gates.text_checks import reflow_soft_linebreaks

    lines = [f"Еженедельный дайджест законодательных изменений ({week_label})", ""]
    for idx, card in enumerate(cards, start=1):
        doc = card.document
        num = doc.number or "—"
        title = (doc.name or doc.eo_number)[:120]
        lines.append(f"{idx}. №{num} — {title}")
        lines.append(reflow_soft_linebreaks(card.card.content.strip()))
        if doc.source_url:
            lines.append(f"Источник: {doc.source_url}")
        lines.append("")
    return "\n".join(lines).strip()


def create_digest_post(
    session: Session,
    cards: list[ScoredCard],
    *,
    today: date | None = None,
    post_type: PostType = PostType.digest,
) -> PostBank | None:
    if not cards:
        return None

    today = today or date.today()
    week_start, week_end = _past_week_bounds(today)
    week_label = f"{week_start.isoformat()} — {week_end.isoformat()}"
    title = f"Дайджест ФЗ ({week_start.strftime('%d.%m')}–{week_end.strftime('%d.%m.%Y')})"
    if post_type == PostType.mini_digest:
        title = f"Мини-дайджест ФЗ ({week_start.strftime('%d.%m.%Y')})"

    post = PostBank(
        title=title,
        content=build_digest_content(cards, week_label=week_label),
        post_type=post_type,
        status=PostStatus.ready,
    )
    session.add(post)
    session.flush()

    for order, card in enumerate(cards):
        session.add(
            PostItem(post_id=post.id, document_id=card.document_id, order_index=order)
        )
        card.document.included_in_post = True
        card.document.significance_score = card.score

    return post


def build_enactment_week_post(session: Session, *, today: date | None = None) -> PostBank | None:
    """Запасной формат: что вступает в силу на этой неделе."""
    today = today or date.today()
    week_start, week_end = _current_week_bounds(today)

    rows = session.execute(
        select(NpaEnactment, NpaDocument)
        .join(NpaDocument, NpaDocument.id == NpaEnactment.document_id)
        .where(
            NpaEnactment.effective_date >= week_start,
            NpaEnactment.effective_date <= week_end,
        )
        .order_by(NpaEnactment.effective_date, NpaDocument.number)
    ).all()

    if not rows:
        return None

    lines = [
        f"Вступает в силу на неделе {week_start.isoformat()} — {week_end.isoformat()}",
        "",
    ]
    seen: set[tuple[int, date]] = set()
    for enactment, doc in rows:
        key = (doc.id, enactment.effective_date)
        if key in seen:
            continue
        seen.add(key)
        num = doc.number or "—"
        title = (doc.name or doc.eo_number)[:100]
        article = (enactment.unit_address or {}).get("статья")
        article_part = f", ст. {article}" if article else ""
        src = f" — {doc.source_url}" if doc.source_url else ""
        lines.append(
            f"• {enactment.effective_date.strftime('%d.%m.%Y')}: №{num}{article_part} — {title}{src}"
        )

    post = PostBank(
        title=f"Вступает в силу ({week_start.strftime('%d.%m')}–{week_end.strftime('%d.%m.%Y')})",
        content="\n".join(lines),
        post_type=PostType.enactment_week,
        status=PostStatus.ready,
    )
    session.add(post)
    session.flush()
    return post

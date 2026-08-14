"""Отбор законов для дайджеста: прошедшие гейты документы, не заранее свёрстанные карточки."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from explainlaw.content.digest import digest_freshness_start
from explainlaw.content.scoring import ScoredCard, score_card
from explainlaw.db.models import (
    GateStatus,
    NpaDelta,
    NpaDocument,
    NpaSummary,
    PostBank,
    PostItem,
    PostType,
)
from explainlaw.gates.post_bank import format_card_content, format_post_title


def _documents_in_digests(session: Session) -> set[int]:
    rows = session.execute(
        select(PostItem.document_id)
        .join(PostBank, PostBank.id == PostItem.post_id)
        .where(PostBank.post_type.in_([PostType.digest, PostType.mini_digest]))
    ).all()
    return {row[0] for row in rows}


def select_cards_for_digest(
    session: Session,
    *,
    max_items: int,
    today: date | None = None,
) -> list[ScoredCard]:
    """Документы с прошедшими гейтами за текущую + прошедшую календарную неделю."""
    today = today or date.today()
    freshness_start = digest_freshness_start(today)
    used_docs = _documents_in_digests(session)
    latest_summary_id = (
        select(func.max(NpaSummary.id))
        .where(NpaSummary.document_id == NpaDocument.id)
        .correlate(NpaDocument)
        .scalar_subquery()
    )
    rows = session.execute(
        select(NpaDocument, NpaSummary, NpaDelta)
        .join(NpaSummary, NpaSummary.document_id == NpaDocument.id)
        .join(NpaDelta, NpaDelta.document_id == NpaDocument.id)
        .options(selectinload(NpaDocument.enactments), selectinload(NpaDocument.text))
        .where(
            NpaSummary.id == latest_summary_id,
            NpaSummary.gate_status == GateStatus.passed,
            NpaDocument.publish_date_short >= freshness_start,
        )
        .order_by(NpaDocument.publish_date_short.desc())
    ).all()

    scored: list[ScoredCard] = []
    for doc, summary, delta in rows:
        if doc.id in used_docs or doc.included_in_post:
            continue
        title = format_post_title(doc, summary)
        content = format_card_content(doc, summary, delta)
        scored.append(
            ScoredCard(
                document_id=doc.id,
                document=doc,
                delta=delta,
                title=title,
                content=content,
                score=score_card(doc=doc, delta=delta, today=today, content_len=len(content)),
            )
        )

    scored.sort(key=lambda c: c.score, reverse=True)
    return scored[:max_items]

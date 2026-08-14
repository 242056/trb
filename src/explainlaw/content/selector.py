"""Отбор карточек из банка готовых (§7.2)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from explainlaw.content.digest import digest_freshness_start
from explainlaw.content.scoring import ScoredCard, score_card
from explainlaw.db.models import NpaDelta, NpaDocument, PostBank, PostItem, PostStatus, PostType


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
    """Карточки single/ready за актуальный период (текущая + прошедшая календарная неделя)."""
    today = today or date.today()
    freshness_start = digest_freshness_start(today)
    used_docs = _documents_in_digests(session)
    rows = session.execute(
        select(PostBank, PostItem, NpaDocument, NpaDelta)
        .join(PostItem, PostItem.post_id == PostBank.id)
        .join(NpaDocument, NpaDocument.id == PostItem.document_id)
        .outerjoin(NpaDelta, NpaDelta.document_id == NpaDocument.id)
        .where(
            PostBank.post_type == PostType.single,
            PostBank.status == PostStatus.ready,
            NpaDocument.publish_date_short >= freshness_start,
        )
        .order_by(NpaDocument.publish_date_short.desc())
    ).all()

    scored: list[ScoredCard] = []
    for card, item, doc, delta in rows:
        if doc.id in used_docs:
            continue
        if doc.included_in_post:
            continue
        scored.append(
            ScoredCard(
                post_id=card.id,
                document_id=doc.id,
                document=doc,
                delta=delta,
                card=card,
                score=score_card(doc=doc, delta=delta, card=card, today=today),
            )
        )

    scored.sort(key=lambda c: c.score, reverse=True)
    return scored[:max_items]

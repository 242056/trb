"""Очередь недостающих актов — итерация 2 (§8.3)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from explainlaw.db.models import MissingActStatus, MissingActsQueue
from explainlaw.extraction.act_identifier import find_document_by_identifier, identifier_key


def enqueue_missing_act(
    session: Session,
    *,
    referenced_act_identifier: dict,
    referencing_document_id: int,
) -> bool:
    """
    Записывает запрос на недостающий акт.
    Возвращает True, если акт добавлен/обновлён в очереди; False если уже есть в базе.
    """
    if find_document_by_identifier(session, referenced_act_identifier) is not None:
        return False

    key = identifier_key(referenced_act_identifier)
    existing = session.execute(select(MissingActsQueue)).scalars().all()
    for row in existing:
        if identifier_key(row.referenced_act_identifier) == key:
            row.request_count += 1
            row.referencing_document_id = referencing_document_id
            return True

    session.add(
        MissingActsQueue(
            referenced_act_identifier=referenced_act_identifier,
            referencing_document_id=referencing_document_id,
            status=MissingActStatus.pending,
            request_count=1,
        )
    )
    return True


def enqueue_from_relations(
    session: Session,
    *,
    document_id: int,
    relations: list,
) -> int:
    """Ставит в очередь все цели связей, которых нет в базе."""
    enqueued = 0
    for rel in relations:
        if enqueue_missing_act(
            session,
            referenced_act_identifier=rel.target_act_identifier,
            referencing_document_id=document_id,
        ):
            enqueued += 1
    return enqueued

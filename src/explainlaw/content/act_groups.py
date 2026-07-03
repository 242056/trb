"""Группировка родственных ФЗ — пакеты поправок (§4.4)."""

from __future__ import annotations

import re
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from explainlaw.db.models import NpaDocument, NpaRelation

_BUNDLE_RE = re.compile(
    r"отдельн\w+\s+законодательн\w+\s+акт",
    re.IGNORECASE,
)
_MULTI_CODE_RE = re.compile(
    r"кодекс\w*\s+российской\s+федерации",
    re.IGNORECASE,
)


def _normalize_bundle_key(name: str | None) -> str:
    if not name:
        return "unknown"
    cleaned = re.sub(r"\s+", " ", name.strip().lower())
    if _BUNDLE_RE.search(cleaned):
        return "bundle:separate_acts"
    if _MULTI_CODE_RE.search(cleaned):
        return "bundle:codes"
    match = re.search(r"внести изменения в (.+)", cleaned)
    if match:
        return f"target:{match.group(1)[:120]}"
    return cleaned[:120]


def _group_uuid(publish_date: date | None, key: str) -> uuid.UUID:
    day = publish_date.isoformat() if publish_date else "unknown"
    return uuid.uuid5(uuid.NAMESPACE_URL, f"explainlaw:act-group:{day}:{key}")


def assign_act_group(session: Session, doc: NpaDocument) -> uuid.UUID | None:
    """Назначает act_group_id документу по дате публикации и целевому акту/пакету."""
    key = _normalize_bundle_key(doc.name)
    group_id = _group_uuid(doc.publish_date_short, key)

    relation = session.execute(
        select(NpaRelation)
        .where(NpaRelation.source_document_id == doc.id)
        .limit(1)
    ).scalar_one_or_none()
    if relation and relation.target_act_identifier:
        target = relation.target_act_identifier
        target_key = target.get("number") or target.get("name") or ""
        if target_key:
            group_id = _group_uuid(doc.publish_date_short, f"rel:{target_key}")

    if doc.act_group_id == group_id:
        return group_id

    doc.act_group_id = group_id
    return group_id

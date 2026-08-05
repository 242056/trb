"""Формирование дельты — итерация 3a (§8.3, только full_redaction)."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from explainlaw.db.models import (
    ApplyKind,
    DeltaCompleteness,
    NpaDelta,
    NpaDocument,
    NpaText,
    NormChangeEvent,
)
from explainlaw.extraction.act_identifier import find_document_by_identifier
from explainlaw.extraction.article_text import extract_article_text
from explainlaw.gates.text_checks import verify_quote_in_source


def build_delta_for_document(session: Session, doc: NpaDocument, source_text: str) -> NpaDelta | None:
    """Строит npa_delta из norm_change_event документа."""
    events = session.execute(
        select(NormChangeEvent)
        .options(selectinload(NormChangeEvent.norm))
        .where(NormChangeEvent.source_document_id == doc.id)
        .order_by(NormChangeEvent.effective_date, NormChangeEvent.apply_order)
    ).scalars().all()

    if not events:
        return None

    changes: list[dict[str, Any]] = []
    has_full = False
    has_partial = False

    for event in events:
        parent_act = event.norm.parent_act_identifier if event.norm else {}
        target_doc = find_document_by_identifier(session, parent_act)
        text_before: str | None = None
        completeness = "partial"

        article = (event.unit_address or {}).get("статья")
        if target_doc and article:
            text_row = session.execute(
                select(NpaText).where(NpaText.document_id == target_doc.id)
            ).scalar_one_or_none()
            if text_row:
                text_before = extract_article_text(text_row.full_text, str(article))

        if event.apply_kind == ApplyKind.full_redaction and text_before and event.text_after:
            completeness = "full"
            has_full = True
        elif event.apply_kind == ApplyKind.address_patch:
            completeness = "partial"
            has_partial = True
        else:
            has_partial = True

        quote_ok = verify_quote_in_source(event.text_after, source_text)

        changes.append(
            {
                "unit_address": event.unit_address,
                "operation_type": event.operation_type.value,
                "apply_kind": event.apply_kind.value,
                "target_act": parent_act,
                "target_in_database": target_doc is not None,
                "text_before": text_before,
                "text_after": event.text_after,
                "effective_date": event.effective_date.isoformat(),
                "completeness": completeness,
                "quote_verified": quote_ok,
            }
        )

    if has_full and not has_partial:
        status = DeltaCompleteness.full
    else:
        status = DeltaCompleteness.partial

    delta_data = {
        "changes": changes,
        "change_count": len(changes),
        "built_at": date.today().isoformat(),
    }

    existing = session.execute(
        select(NpaDelta).where(NpaDelta.document_id == doc.id)
    ).scalar_one_or_none()

    if existing:
        existing.completeness_status = status
        existing.delta_data = delta_data
        return existing

    row = NpaDelta(
        document_id=doc.id,
        completeness_status=status,
        delta_data=delta_data,
    )
    session.add(row)
    return row

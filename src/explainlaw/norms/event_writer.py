import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from explainlaw.db.models import (
    ApplyKind,
    ApplyStatus,
    Norm,
    NormChangeEvent,
    NormEventType,
    OperationType,
)
from explainlaw.extraction.article_text import extract_article_text

logger = logging.getLogger(__name__)

_QWEN_SYSTEM = """Ты обработчик юридического текста. Извлеки структурированные изменения ТОЛЬКО из предъявленного фрагмента.
Верни JSON:
{
  "changes": [
    {
      "unit_address": {"статья": "1", "часть": null, "пункт": null},
      "operation_type": "full_redaction|replace|supplement|delete",
      "apply_kind": "full_redaction|address_patch",
      "text_after": "текст новой редакции если есть дословно во фрагменте"
    }
  ]
}
Не выдумывай текст. Если данных нет — верни {"changes": []}."""

_FULL_REDACTION_RE = re.compile(
    r"стать(?:ю|и|я)\s+(\d+(?:\.\d+)?)\s+.*?изложить\s+(?:в\s+)?(?:следующей\s+)?редакции",
    re.IGNORECASE | re.DOTALL,
)

_INLINE_ARTICLE_REDACTION_RE = re.compile(
    r"изложить\s+(?:в\s+)?(?:следующей\s+)?редакции\s*:?\s*(.{80,2000})",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class NormChangeDraft:
    unit_address: dict[str, Any]
    operation_type: OperationType
    apply_kind: ApplyKind
    text_after: str | None
    effective_date: date | None


def _qwen_client():
    from explainlaw.llm.factory import create_qwen_client

    return create_qwen_client()


def _regex_extract(fragment: str) -> list[NormChangeDraft]:
    drafts: list[NormChangeDraft] = []
    for match in _FULL_REDACTION_RE.finditer(fragment):
        article = match.group(1)
        after_start = match.end()
        text_after = fragment[after_start : after_start + 2000].strip()
        drafts.append(
            NormChangeDraft(
                unit_address={"статья": article},
                operation_type=OperationType.full_redaction,
                apply_kind=ApplyKind.full_redaction,
                text_after=text_after or None,
                effective_date=None,
            )
        )
    if drafts:
        return drafts

    inline = _INLINE_ARTICLE_REDACTION_RE.search(fragment)
    if inline:
        article_match = re.search(
            r"стать(?:ю|и|я)\s+(\d+(?:\.\d+)?)", fragment[: inline.start()], re.IGNORECASE
        )
        article = article_match.group(1) if article_match else "1"
        drafts.append(
            NormChangeDraft(
                unit_address={"статья": article},
                operation_type=OperationType.full_redaction,
                apply_kind=ApplyKind.full_redaction,
                text_after=inline.group(1).strip() or None,
                effective_date=None,
            )
        )
    return drafts


def _qwen_extract(fragment: str) -> list[NormChangeDraft]:
    client = _qwen_client()
    if not client.available:
        return []

    try:
        data = client.chat_json(system=_QWEN_SYSTEM, user=fragment)
    except Exception:
        logger.exception("Qwen extraction failed")
        return []

    drafts: list[NormChangeDraft] = []
    for item in data.get("changes", []):
        op = item.get("operation_type", "replace")
        kind = item.get("apply_kind", "address_patch")
        try:
            operation_type = OperationType(op)
        except ValueError:
            operation_type = OperationType.replace
        try:
            apply_kind = ApplyKind(kind)
        except ValueError:
            apply_kind = ApplyKind.address_patch

        drafts.append(
            NormChangeDraft(
                unit_address=item.get("unit_address") or {},
                operation_type=operation_type,
                apply_kind=apply_kind,
                text_after=item.get("text_after"),
                effective_date=None,
            )
        )
    return drafts


def extract_norm_changes(fragment: str) -> list[NormChangeDraft]:
    drafts = _qwen_extract(fragment)
    if drafts:
        return drafts
    return _regex_extract(fragment)


def _stable_norm_id(parent_act: dict, unit_address: dict) -> str:
    article = unit_address.get("статья", "unknown")
    act_key = (
        parent_act.get("number")
        or parent_act.get("date")
        or parent_act.get("name", "act")
    )
    raw = f"{act_key}::ст{article}"
    if len(raw) <= 120:
        return raw
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _ensure_baseline(
    session: Session,
    norm: Norm,
    *,
    text_before: str,
    effective_date: date,
    source_document_id: int,
    raw_reference_id: int | None,
) -> None:
    existing = session.execute(
        select(NormChangeEvent)
        .where(
            NormChangeEvent.norm_id == norm.id,
            NormChangeEvent.event_type == NormEventType.baseline,
        )
        .limit(1)
    ).scalars().first()
    if existing:
        return

    session.add(
        NormChangeEvent(
            norm_id=norm.id,
            source_document_id=source_document_id,
            event_type=NormEventType.baseline,
            effective_date=effective_date,
            apply_order=-1,
            operation_type=OperationType.full_redaction,
            unit_address=norm.unit_address,
            text_before=None,
            text_after=text_before,
            apply_kind=ApplyKind.full_redaction,
            apply_status=ApplyStatus.applied,
            raw_reference_id=raw_reference_id,
        )
    )


def persist_norm_changes(
    session: Session,
    *,
    source_document_id: int,
    parent_act_identifier: dict,
    enactment_date: date | None,
    drafts: list[NormChangeDraft],
    raw_reference_id: int | None = None,
    target_full_text: str | None = None,
    apply_order_start: int = 0,
) -> int:
    written = 0
    effective_default = enactment_date or date.today()

    for idx, draft in enumerate(drafts):
        stable_id = _stable_norm_id(parent_act_identifier, draft.unit_address)
        norm = session.execute(
            select(Norm).where(Norm.stable_norm_id == stable_id)
        ).scalar_one_or_none()
        if norm is None:
            try:
                with session.begin_nested():
                    norm = Norm(
                        stable_norm_id=stable_id,
                        parent_act_identifier=parent_act_identifier,
                        unit_address=draft.unit_address,
                    )
                    session.add(norm)
                    session.flush()
            except Exception as exc:
                # UniqueViolation на concurrent insert — перечитываем
                from sqlalchemy.exc import IntegrityError

                if not isinstance(exc, IntegrityError):
                    raise
                norm = session.execute(
                    select(Norm).where(Norm.stable_norm_id == stable_id)
                ).scalar_one()

        article = (draft.unit_address or {}).get("статья")
        text_before = None
        if target_full_text and article:
            text_before = extract_article_text(target_full_text, str(article))

        if text_before:
            _ensure_baseline(
                session,
                norm,
                text_before=text_before,
                effective_date=effective_default,
                source_document_id=source_document_id,
                raw_reference_id=raw_reference_id,
            )

        apply_status = (
            ApplyStatus.needs_manual
            if draft.apply_kind == ApplyKind.address_patch
            else ApplyStatus.applied if draft.text_after else ApplyStatus.needs_manual
        )

        event = NormChangeEvent(
            norm_id=norm.id,
            source_document_id=source_document_id,
            event_type=NormEventType.amendment,
            effective_date=draft.effective_date or effective_default,
            apply_order=apply_order_start + idx,
            operation_type=draft.operation_type,
            unit_address=draft.unit_address,
            text_before=text_before,
            text_after=draft.text_after,
            apply_kind=draft.apply_kind,
            apply_status=apply_status,
            raw_reference_id=raw_reference_id,
        )
        session.add(event)
        session.flush()

        if (
            draft.apply_kind == ApplyKind.full_redaction
            and draft.text_after
            and apply_status == ApplyStatus.applied
        ):
            from explainlaw.norms.revision import NormRevisionAssembler

            assembler = NormRevisionAssembler(session)
            assembler.invalidate_cache_for_norm(norm.id)
            assembler.get_revision(norm.id, event.effective_date)

        written += 1

    return written

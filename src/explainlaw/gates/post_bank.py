"""Помещение прошедших гейты карточек в банк готовых (§9.3, итерация 4)."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from explainlaw.db.models import NpaDelta, NpaDocument, NpaSummary, PostBank, PostItem, PostStatus, PostType


def _short_title(name: str | None, max_len: int = 80) -> str:
    if not name:
        return "Федеральный закон"
    title = re.sub(r"\s+", " ", name.strip().strip('"«»'))
    return title if len(title) <= max_len else title[: max_len - 1] + "…"


def _format_card_content(doc: NpaDocument, summary: NpaSummary, delta: NpaDelta) -> str:
    lines = [summary.summary_text.strip(), ""]
    changes = delta.delta_data.get("changes") or []
    if not changes:
        return "\n".join(lines)

    lines.append("Изменения:")
    for change in changes[:5]:
        target = change.get("target_act") or {}
        target_label = target.get("number") or target.get("name") or "акт"
        article = (change.get("unit_address") or {}).get("статья")
        article_part = f", ст. {article}" if article else ""
        after = (change.get("text_after") or "")[:200]
        lines.append(f"• {target_label}{article_part}: {after}")
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
        title=f"№{number} — {_short_title(doc.name)}",
        content=_format_card_content(doc, summary, delta),
        post_type=PostType.single,
        status=PostStatus.ready,
    )
    session.add(post)
    session.flush()
    session.add(PostItem(post_id=post.id, document_id=doc.id, order_index=0))
    return post.id, True

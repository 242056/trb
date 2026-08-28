"""Оценка значимости документов для ежедневного отбора (§7.2)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from explainlaw.db.models import DeltaCompleteness, NpaDelta, NpaDocument


@dataclass
class ScoredCard:
    document_id: int
    document: NpaDocument
    delta: NpaDelta | None
    title: str
    content: str
    score: float


def score_card(
    *,
    doc: NpaDocument,
    delta: NpaDelta | None,
    today: date | None = None,
    content_len: int = 0,
) -> float:
    """Чем выше — тем приоритетнее для дайджеста."""
    today = today or date.today()
    score = 0.0

    if delta:
        if delta.completeness_status == DeltaCompleteness.full:
            score += 40.0
        else:
            score += 15.0
        change_count = delta.delta_data.get("change_count") or len(delta.delta_data.get("changes") or [])
        score += min(change_count * 3.0, 15.0)

    if doc.pages_count:
        score += min(doc.pages_count / 10.0, 10.0)

    if doc.publish_date_short:
        age_days = (today - doc.publish_date_short).days
        if age_days <= 7:
            score += 20.0
        elif age_days <= 30:
            score += 10.0
        elif age_days <= 90:
            score += 5.0

    if doc.significance_score is not None:
        score += doc.significance_score

    score += min(content_len / 500.0, 5.0)

    return score

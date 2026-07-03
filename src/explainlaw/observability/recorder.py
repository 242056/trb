"""Запись метрик запусков конвейера (§11)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from explainlaw.db.models import PipelineJobType, PipelineRun, PipelineRunStatus


def _resolve_status(metrics: dict[str, Any]) -> PipelineRunStatus:
    errors = metrics.get("errors", 0)
    if errors and not any(metrics.get(k) for k in ("new", "summarized", "passed", "fetched", "digest_created")):
        return PipelineRunStatus.failed
    if errors:
        return PipelineRunStatus.partial
    return PipelineRunStatus.success


def record_run(
    session: Session,
    *,
    job_type: PipelineJobType,
    metrics: dict[str, Any],
    error_message: str | None = None,
) -> PipelineRun:
    status = PipelineRunStatus.failed if error_message else _resolve_status(metrics)
    row = PipelineRun(
        job_type=job_type,
        status=status,
        metrics=metrics,
        error_message=error_message,
        finished_at=datetime.now(timezone.utc),
    )
    session.add(row)
    session.flush()
    return row

"""Проверка здоровья конвейера и алерты на тихий сбой (§11)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from explainlaw.config import settings
from explainlaw.db.models import PipelineJobType, PipelineRun, PipelineRunStatus

logger = logging.getLogger(__name__)


def check_health(session: Session) -> dict[str, Any]:
    alerts: list[dict[str, str]] = []
    now = datetime.now(timezone.utc)

    last_collect = session.execute(
        select(PipelineRun)
        .where(
            PipelineRun.job_type == PipelineJobType.collect,
            PipelineRun.status.in_([PipelineRunStatus.success, PipelineRunStatus.partial]),
        )
        .order_by(desc(PipelineRun.started_at))
        .limit(1)
    ).scalar_one_or_none()

    if last_collect is None:
        alerts.append(
            {
                "type": "collect_never_ran",
                "message": "Успешный сбор ещё ни разу не выполнялся",
            }
        )
    else:
        age = now - last_collect.started_at
        if age > timedelta(hours=settings.collect_silent_alert_hours):
            alerts.append(
                {
                    "type": "collect_silent",
                    "message": (
                        f"Нет успешного сбора {int(age.total_seconds() // 3600)} ч "
                        f"(порог {settings.collect_silent_alert_hours} ч)"
                    ),
                    "last_run": last_collect.started_at.isoformat(),
                }
            )

    last_daily = session.execute(
        select(PipelineRun)
        .where(PipelineRun.job_type == PipelineJobType.daily)
        .order_by(desc(PipelineRun.started_at))
        .limit(1)
    ).scalar_one_or_none()

    recent_runs = session.execute(
        select(PipelineRun).order_by(desc(PipelineRun.started_at)).limit(10)
    ).scalars().all()

    return {
        "healthy": len(alerts) == 0,
        "alerts": alerts,
        "last_collect": {
            "at": last_collect.started_at.isoformat() if last_collect else None,
            "metrics": last_collect.metrics if last_collect else None,
            "status": last_collect.status.value if last_collect else None,
        },
        "last_daily": {
            "at": last_daily.started_at.isoformat() if last_daily else None,
            "status": last_daily.status.value if last_daily else None,
        },
        "recent_runs": [
            {
                "job_type": r.job_type.value,
                "status": r.status.value,
                "started_at": r.started_at.isoformat(),
                "metrics": r.metrics,
            }
            for r in recent_runs
        ],
    }


def send_alert_webhook(health: dict[str, Any]) -> bool:
    if not settings.alert_webhook_url or health.get("healthy"):
        return False

    payload = {
        "text": "ExplainLaw: " + "; ".join(a["message"] for a in health.get("alerts", [])),
        "alerts": health.get("alerts"),
    }
    try:
        response = httpx.post(
            settings.alert_webhook_url,
            json=payload,
            timeout=10.0,
        )
        response.raise_for_status()
        return True
    except Exception:
        logger.exception("Не удалось отправить алерт")
        return False

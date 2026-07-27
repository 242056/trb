"""Проверка здоровья конвейера и алерты на тихий сбой (§11)."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
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


def _append_alert_log(health: dict[str, Any]) -> None:
    path = Path(settings.alert_log_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "healthy": health.get("healthy"),
            "alerts": health.get("alerts"),
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        logger.exception("Не удалось записать alert log %s", path)


def _telegram_alert_budget_remaining(*, today: date | None = None) -> bool:
    """True, если ещё можно слать TG-алерт сегодня (лимит ALERT_TELEGRAM_MAX_PER_DAY)."""
    limit = settings.alert_telegram_max_per_day
    if limit <= 0:
        return True
    today = today or datetime.now(timezone.utc).date()
    path = Path(settings.alert_telegram_state_path)
    try:
        if not path.exists():
            return True
        data = json.loads(path.read_text(encoding="utf-8"))
        day = data.get("day")
        count = int(data.get("count") or 0)
        if day != today.isoformat():
            return True
        return count < limit
    except Exception:
        logger.exception("Не удалось прочитать %s", path)
        return True


def _record_telegram_alert_sent(*, today: date | None = None) -> None:
    today = today or datetime.now(timezone.utc).date()
    path = Path(settings.alert_telegram_state_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        count = 1
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("day") == today.isoformat():
                    count = int(data.get("count") or 0) + 1
            except Exception:
                count = 1
        path.write_text(
            json.dumps(
                {
                    "day": today.isoformat(),
                    "count": count,
                    "last_at": datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    except Exception:
        logger.exception("Не удалось записать %s", path)


def send_alert_webhook(health: dict[str, Any]) -> bool:
    if health.get("healthy") or not settings.alert_webhook_url:
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
        logger.exception("Не удалось отправить webhook-алерт")
        return False


def send_telegram_alert(health: dict[str, Any]) -> bool:
    if health.get("healthy"):
        return False
    if not _telegram_alert_budget_remaining():
        logger.info(
            "Telegram-алерт пропущен: лимит %s/сутки уже исчерпан",
            settings.alert_telegram_max_per_day,
        )
        return False
    from explainlaw.messaging.telegram import format_alert_for_telegram, send_telegram_text

    messages = [a["message"] for a in health.get("alerts", [])]
    if not messages:
        return False
    ok = send_telegram_text(format_alert_for_telegram(messages))
    if ok:
        _record_telegram_alert_sent()
    return ok


def send_alerts(health: dict[str, Any]) -> bool:
    """Файл-лог + webhook + Telegram при проблемах. Возвращает True если что-то ушло наружу."""
    if health.get("healthy"):
        return False
    _append_alert_log(health)
    sent_webhook = send_alert_webhook(health)
    sent_tg = send_telegram_alert(health)
    return sent_webhook or sent_tg

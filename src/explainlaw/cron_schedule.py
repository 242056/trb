"""Генерация crontab для supercronic из Settings / env."""

from __future__ import annotations

import os

from explainlaw.config import Settings

EXPLAINLAW_DEFAULT = "/usr/local/bin/explainlaw"


def render_crontab(settings: Settings | None = None) -> str:
    """Вернуть текст crontab."""
    if settings is None:
        settings = Settings()

    bin_path = os.environ.get("EXPLAINLAW_BIN", EXPLAINLAW_DEFAULT)
    lines: list[str] = [
        f"# Generated crontab (TZ hint: {settings.cron_timezone})",
        "# Times are interpreted in the container timezone (set TZ env).",
    ]

    process_limit = settings.pipeline_process_limit
    fetch_missing = settings.pipeline_fetch_missing_limit
    backfill_limit = settings.pipeline_backfill_limit

    daily_args = ["daily"]
    if process_limit is not None:
        daily_args += ["--process-limit", str(process_limit)]
    daily_args += ["--fetch-missing", str(fetch_missing)]
    daily_cmd = " ".join([bin_path, *daily_args])

    weekly_cmd = f"{daily_cmd} --weekly-publish"
    backfill_cmd = f"{bin_path} rebuild-deltas --resume --limit {backfill_limit}"
    health_cmd = f"{bin_path} health --alert"

    jobs = [
        (settings.cron_daily_enabled, settings.cron_daily_schedule, daily_cmd, "daily pipeline"),
        (
            settings.cron_weekly_enabled,
            settings.cron_weekly_schedule,
            weekly_cmd,
            "weekly digest + Telegram",
        ),
        (
            settings.cron_backfill_enabled,
            settings.cron_backfill_schedule,
            backfill_cmd,
            "delta backfill",
        ),
        (
            settings.cron_health_enabled,
            settings.cron_health_schedule,
            health_cmd,
            "health + alerts",
        ),
    ]

    for enabled, schedule, command, comment in jobs:
        if not enabled:
            lines.append(f"# disabled: {comment}")
            continue
        schedule = (schedule or "").strip()
        if not schedule:
            lines.append(f"# skipped empty schedule: {comment}")
            continue
        lines.append(f"# {comment}")
        lines.append(f"{schedule} {command}")

    return "\n".join(lines) + "\n"

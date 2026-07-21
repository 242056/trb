"""Тесты генерации crontab из Settings."""

from explainlaw.config import Settings
from explainlaw.cron_schedule import render_crontab


def test_render_crontab_defaults():
    text = render_crontab(Settings(_env_file=None))
    assert "/usr/local/bin/explainlaw daily" in text
    assert "--weekly-publish" in text
    assert "rebuild-deltas --resume --limit 500" in text
    assert "health --alert" in text
    assert "0 8 * * *" in text
    assert "0 9 * * 1" in text


def test_render_crontab_custom_schedule_and_limits():
    s = Settings(
        _env_file=None,
        cron_daily_schedule="*/5 * * * *",
        cron_weekly_enabled=False,
        pipeline_process_limit=7,
        pipeline_fetch_missing_limit=2,
        pipeline_backfill_limit=10,
    )
    text = render_crontab(s)
    assert "*/5 * * * * /usr/local/bin/explainlaw daily --process-limit 7 --fetch-missing 2" in text
    assert "disabled: weekly" in text
    assert "rebuild-deltas --resume --limit 10" in text


def test_empty_pipeline_limit_env():
    s = Settings(_env_file=None, pipeline_process_limit="")  # type: ignore[arg-type]
    assert s.pipeline_process_limit is None

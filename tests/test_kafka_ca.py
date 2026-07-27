"""Тесты Kafka CA и лимита Telegram-алертов."""

import json
import os
from datetime import date
from pathlib import Path

from explainlaw.config import settings
from explainlaw.messaging.kafka import resolve_kafka_ssl_ca_location
from explainlaw.observability import health as health_mod


def test_resolve_uses_existing_configured(tmp_path: Path):
    ca = tmp_path / "custom.crt"
    ca.write_text("cert")
    assert resolve_kafka_ssl_ca_location(str(ca)) == str(ca)


def test_resolve_falls_back_when_missing(tmp_path: Path, monkeypatch):
    missing = str(tmp_path / "nope.crt")
    docker_ca = "/usr/local/share/ca-certificates/Yandex/YandexInternalRootCA.crt"
    real_isfile = os.path.isfile

    def fake_isfile(path: str) -> bool:
        if path == missing:
            return False
        if path == docker_ca:
            return True
        return real_isfile(path)

    monkeypatch.setattr(os.path, "isfile", fake_isfile)
    assert resolve_kafka_ssl_ca_location(missing) == docker_ca


def test_telegram_alert_budget_one_per_day(tmp_path: Path, monkeypatch):
    state = tmp_path / "alert_telegram_state.json"
    monkeypatch.setattr(settings, "alert_telegram_state_path", str(state))
    monkeypatch.setattr(settings, "alert_telegram_max_per_day", 1)
    today = date(2026, 7, 27)
    assert health_mod._telegram_alert_budget_remaining(today=today) is True
    health_mod._record_telegram_alert_sent(today=today)
    data = json.loads(state.read_text(encoding="utf-8"))
    assert data["day"] == "2026-07-27"
    assert data["count"] == 1
    assert health_mod._telegram_alert_budget_remaining(today=today) is False
    assert health_mod._telegram_alert_budget_remaining(today=date(2026, 7, 28)) is True

"""Тесты резолва Kafka CA (Docker vs хостовый путь)."""

import os
from pathlib import Path

from explainlaw.messaging.kafka import resolve_kafka_ssl_ca_location


def test_resolve_uses_existing_configured(tmp_path: Path, monkeypatch):
    ca = tmp_path / "custom.crt"
    ca.write_text("cert")
    assert resolve_kafka_ssl_ca_location(str(ca)) == str(ca)


def test_resolve_falls_back_when_missing(tmp_path: Path, monkeypatch):
    missing = str(tmp_path / "nope.crt")
    docker_ca = "/usr/local/share/ca-certificates/Yandex/YandexInternalRootCA.crt"
    # If docker CA exists on this machine use it; else create a fake via monkeypatch isfile
    real_isfile = os.path.isfile

    def fake_isfile(path: str) -> bool:
        if path == missing:
            return False
        if path == docker_ca:
            return True
        return real_isfile(path)

    monkeypatch.setattr(os.path, "isfile", fake_isfile)
    assert resolve_kafka_ssl_ca_location(missing) == docker_ca

import os

from explainlaw.config import Settings


def test_aws_aliases_map_to_minio(monkeypatch):
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://storage.yandexcloud.net")
    monkeypatch.setenv("AWS_KEY_ID", "test-key")
    monkeypatch.setenv("AWS_SECRET_KEY", "test-secret")
    monkeypatch.setenv("AWS_BUCKET", "explain-npa")
    # сброс возможных MINIO из окружения агента
    for key in (
        "MINIO_ENDPOINT",
        "MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY",
        "MINIO_BUCKET_RAW",
        "MINIO_BUCKET_SNAPSHOTS",
    ):
        monkeypatch.delenv(key, raising=False)

    s = Settings(_env_file=None)
    assert s.minio_endpoint == "https://storage.yandexcloud.net"
    assert s.minio_access_key == "test-key"
    assert s.minio_secret_key == "test-secret"
    assert s.minio_bucket_raw == "explain-npa"
    assert s.minio_bucket_snapshots == "explain-npa"
    assert s.minio_secure is True
    assert s.minio_region == "ru-central1"


def test_parse_endpoint_https():
    from explainlaw.storage.object_store import _parse_endpoint

    host, secure = _parse_endpoint("https://storage.yandexcloud.net")
    assert host == "storage.yandexcloud.net"
    assert secure is True

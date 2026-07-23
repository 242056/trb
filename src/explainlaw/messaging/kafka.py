"""Kafka producer для конвейера (§8.2) и общий конфиг (Yandex SASL_SSL)."""

from __future__ import annotations

import logging
import os
from collections.abc import Generator
from contextlib import contextmanager

from confluent_kafka import Producer

from explainlaw.config import settings

logger = logging.getLogger(__name__)

# Путь CA внутри Docker-образа (как в explain-law/local-llm-worker)
_DOCKER_YANDEX_CA = "/usr/local/share/ca-certificates/Yandex/YandexInternalRootCA.crt"
_FALLBACK_CAS = (
    _DOCKER_YANDEX_CA,
    "/certs/YandexCA.crt",
    "/certs/YandexInternalRootCA.crt",
)


def resolve_kafka_ssl_ca_location(configured: str | None = None) -> str:
    """Вернуть существующий файл CA; хостовый путь из .env в Docker игнорируем."""
    candidates: list[str] = []
    raw = (configured if configured is not None else settings.kafka_ssl_ca_location or "").strip()
    if raw:
        candidates.append(raw)
    for path in _FALLBACK_CAS:
        if path not in candidates:
            candidates.append(path)
    for path in candidates:
        if os.path.isfile(path):
            if raw and path != raw:
                logger.warning(
                    "KAFKA_SSL_CA_LOCATION=%s недоступен, используем %s",
                    raw,
                    path,
                )
            return path
    if raw:
        logger.error("Kafka CA не найден: %s (и fallbacks %s)", raw, _FALLBACK_CAS)
        return raw
    return ""


def kafka_common_config() -> dict:
    conf: dict = {"bootstrap.servers": settings.kafka_bootstrap_servers}
    if settings.kafka_username:
        conf.update(
            {
                "security.protocol": settings.kafka_security_protocol,
                "sasl.mechanisms": settings.kafka_sasl_mechanism,
                "sasl.username": settings.kafka_username,
                "sasl.password": settings.kafka_password,
            }
        )
        ca = resolve_kafka_ssl_ca_location()
        if ca:
            conf["ssl.ca.location"] = ca
    return conf


def create_kafka_producer() -> Producer | None:
    if not settings.kafka_enabled or not settings.kafka_pipeline_events:
        return None
    return Producer({**kafka_common_config(), "acks": "all", "linger.ms": 50})


@contextmanager
def kafka_producer() -> Generator[Producer | None, None, None]:
    producer = create_kafka_producer()
    try:
        yield producer
    finally:
        if producer is not None:
            try:
                producer.flush(15)
            except Exception:
                logger.exception("Kafka flush failed")

"""Kafka producer для конвейера (§8.2) и общий конфиг (Yandex SASL_SSL)."""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager

from confluent_kafka import Producer

from explainlaw.config import settings

logger = logging.getLogger(__name__)


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
        if settings.kafka_ssl_ca_location:
            conf["ssl.ca.location"] = settings.kafka_ssl_ca_location
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

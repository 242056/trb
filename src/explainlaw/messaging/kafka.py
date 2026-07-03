"""Kafka producer для конвейера (§8.2)."""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager

from confluent_kafka import Producer

from explainlaw.config import settings

logger = logging.getLogger(__name__)


def create_kafka_producer() -> Producer | None:
    if not settings.kafka_enabled:
        return None
    return Producer(
        {
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "acks": "all",
            "linger.ms": 50,
        }
    )


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

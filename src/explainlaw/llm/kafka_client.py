"""Qwen через Kafka: llm.requests → worker → llm.responses."""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from confluent_kafka import Consumer, KafkaError, Producer

from explainlaw.config import settings
from explainlaw.llm.json_utils import parse_json_lenient
from explainlaw.messaging.kafka import kafka_common_config

logger = logging.getLogger(__name__)


class KafkaLLMClient:
    """Совместим с ChatClient (chat / chat_json)."""

    def __init__(
        self,
        *,
        model: str,
        requests_topic: str,
        responses_topic: str,
        group_id: str,
        timeout_sec: float,
    ) -> None:
        self._model = model
        self._requests_topic = requests_topic
        self._responses_topic = responses_topic
        self._group_id = group_id
        self._timeout_sec = timeout_sec
        self._producer = Producer({**kafka_common_config(), "acks": "all"})

    @property
    def available(self) -> bool:
        return bool(settings.kafka_bootstrap_servers and settings.kafka_username)

    def chat(self, *, system: str, user: str, temperature: float = 0.1) -> str:
        correlation_id = str(uuid.uuid4())
        prompt = f"{system.strip()}\n\n{user.strip()}"
        payload = {
            "correlation_id": correlation_id,
            "prompt": prompt,
            "model": self._model,
            "options": {"temperature": temperature},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        # Важно: подписаться на responses ДО produce. Иначе быстрый worker
        # успевает ответить, а consumer с auto.offset.reset=latest ответ пропускает.
        consumer = Consumer(
            {
                **kafka_common_config(),
                "group.id": f"{self._group_id}-{correlation_id[:8]}",
                "auto.offset.reset": "latest",
                "enable.auto.commit": False,
            }
        )
        consumer.subscribe([self._responses_topic])
        deadline = time.time() + self._timeout_sec
        try:
            assign_deadline = min(deadline, time.time() + 10.0)
            while time.time() < assign_deadline and not consumer.assignment():
                consumer.poll(0.2)
            if not consumer.assignment():
                raise TimeoutError("LLM Kafka: нет assignment на llm.responses")

            self._producer.produce(
                self._requests_topic,
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                key=correlation_id.encode("utf-8"),
            )
            self._producer.flush(10)

            while time.time() < deadline:
                msg = consumer.poll(1.0)
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    raise RuntimeError(msg.error())
                data = json.loads(msg.value().decode("utf-8"))
                if data.get("correlation_id") != correlation_id:
                    continue
                if data.get("status") != "ok":
                    raise RuntimeError(data.get("error") or "llm worker error")
                return (data.get("text") or "").strip()
            raise TimeoutError(f"LLM Kafka timeout {self._timeout_sec}s")
        finally:
            consumer.close()

    def chat_json(self, *, system: str, user: str) -> dict[str, Any]:
        raw = self.chat(system=system, user=user, temperature=0.0)
        return parse_json_lenient(raw)

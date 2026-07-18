"""Фабрика LLM-клиентов: Kafka (Qwen) или HTTP."""

from __future__ import annotations

from explainlaw.config import settings
from explainlaw.llm.client import ChatClient
from explainlaw.llm.kafka_client import KafkaLLMClient

LLMClient = ChatClient | KafkaLLMClient


def create_qwen_client() -> LLMClient:
    if settings.llm_transport == "kafka":
        return KafkaLLMClient(
            model=settings.qwen_model,
            requests_topic=settings.kafka_llm_requests_topic,
            responses_topic=settings.kafka_llm_responses_topic,
            group_id=settings.kafka_llm_group_id,
            timeout_sec=settings.llm_request_timeout,
        )
    return ChatClient(
        base_url=settings.qwen_api_base,
        api_key=settings.qwen_api_key,
        model=settings.qwen_model,
        timeout=settings.llm_request_timeout,
    )


def create_gateway_client() -> ChatClient:
    return ChatClient(
        base_url=settings.gateway_api_base,
        api_key=settings.gateway_api_key,
        model=settings.gateway_model,
        timeout=settings.llm_request_timeout,
    )

import logging
import re
from dataclasses import dataclass

from explainlaw.config import settings
from explainlaw.db.models import ModelRoute
from explainlaw.llm.client import ChatClient

logger = logging.getLogger(__name__)

_GATEWAY_SYSTEM = """Ты редактор юридических новостей. Переформулируй предъявленные факты кратко и понятно.
Правила:
- Используй ТОЛЬКО информацию из предъявленного контекста.
- Не добавляй фактов, оценок и интерпретаций.
- 2–4 предложения, простой русский язык.
- Укажи номер и дату закона, если они есть в контексте."""


@dataclass
class SummaryResult:
    text: str
    model_route: ModelRoute


def _gateway_client() -> ChatClient:
    return ChatClient(
        base_url=settings.gateway_api_base,
        api_key=settings.gateway_api_key,
        model=settings.gateway_model,
    )


def _clean_title(name: str | None) -> str:
    if not name:
        return ""
    title = name.strip().strip('"«»')
    title = re.sub(r"\s+", " ", title)
    return title


def _fallback_summary(*, number: str | None, document_date: str | None, name: str | None, fragment: str) -> str:
    """Механическая сводка из предъявленного текста — без генерации знаний."""
    title = _clean_title(name)
    header_parts = []
    if number:
        header_parts.append(f"Федеральный закон № {number}")
    if document_date:
        header_parts.append(f"от {document_date}")
    header = " ".join(header_parts)

    body = fragment.strip()
    sentences = re.split(r"(?<=[.!?])\s+", body)
    excerpt = " ".join(sentences[:3]) if sentences else body[:400]
    excerpt = excerpt[:500].strip()

    if header and title:
        return f"{header}: {title}. {excerpt}"
    if title:
        return f"{title}. {excerpt}"
    return excerpt or "Текст закона извлечён; сводка требует ручной проверки."


def generate_summary(
    *,
    number: str | None,
    document_date: str | None,
    name: str | None,
    fragment: str,
) -> SummaryResult:
    context = (
        f"Номер: {number or 'не указан'}\n"
        f"Дата подписания: {document_date or 'не указана'}\n"
        f"Название: {_clean_title(name)}\n\n"
        f"Фрагмент текста закона:\n{fragment}"
    )

    client = _gateway_client()
    if client.available:
        try:
            text = client.chat(system=_GATEWAY_SYSTEM, user=context)
            return SummaryResult(text=text, model_route=ModelRoute.gateway)
        except Exception:
            logger.exception("Gateway недоступен, используем fallback")

    return SummaryResult(
        text=_fallback_summary(
            number=number,
            document_date=document_date,
            name=name,
            fragment=fragment,
        ),
        model_route=ModelRoute.qwen,
    )

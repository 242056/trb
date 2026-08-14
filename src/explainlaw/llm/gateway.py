import logging
import re
from dataclasses import dataclass

from explainlaw.db.models import ModelRoute

logger = logging.getLogger(__name__)

_GATEWAY_SYSTEM = """Ты редактор юридических новостей. Работай только с предъявленным контекстом.
Верни JSON: {"title": "...", "summary": "..."}

title — 5–8 слов, цепляющая суть закона. НЕ официальное название (оно длинное и однотипное
— не помогает читателю понять, стоит ли читать дальше).
summary — 1–2 предложения простым русским языком: что стало иначе и кого это касается.

Правила:
- Используй ТОЛЬКО информацию из предъявленного контекста.
- Не добавляй фактов, оценок, прогнозов и интерпретаций.
- Не пересказывай и не цитируй закон целиком, пиши своими словами.
- Не пиши «вносятся изменения» — пиши, что именно меняется.
- Если из контекста непонятно, что изменилось — верни ровно:
  {"title": "", "summary": "НЕДОСТАТОЧНО ДАННЫХ"}"""


@dataclass
class SummaryResult:
    text: str
    title: str
    model_route: ModelRoute


def _clean_title(name: str | None) -> str:
    if not name:
        return ""
    title = name.strip().strip('"«»')
    title = re.sub(r"\s+", " ", title)
    return title


def _fallback_summary(
    *, number: str | None, document_date: str | None, name: str | None, fragment: str
) -> SummaryResult:
    """Без LLM не выдумываем и не режем сырой текст — карточка уйдёт в разбор."""
    del number, document_date, name, fragment
    return SummaryResult(text="НЕДОСТАТОЧНО ДАННЫХ", title="", model_route=ModelRoute.qwen)


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

    from explainlaw.llm.factory import create_gateway_client, create_qwen_client

    client = create_gateway_client()
    if client.available:
        try:
            data = client.chat_json(system=_GATEWAY_SYSTEM, user=context)
            summary_text = str(data.get("summary") or "").strip()
            if summary_text:
                return SummaryResult(
                    text=summary_text,
                    title=str(data.get("title") or "").strip(),
                    model_route=ModelRoute.gateway,
                )
        except Exception:
            logger.exception("Gateway недоступен, пробуем Qwen на grounded контексте")

    # Qwen допустим как обработчик предъявленного текста (§8.1 / перспектива)
    qwen = create_qwen_client()
    if qwen.available:
        try:
            data = qwen.chat_json(system=_GATEWAY_SYSTEM, user=context)
            summary_text = str(data.get("summary") or "").strip()
            if summary_text:
                return SummaryResult(
                    text=summary_text,
                    title=str(data.get("title") or "").strip(),
                    model_route=ModelRoute.qwen,
                )
        except Exception:
            logger.exception("Qwen недоступен, используем механический fallback")

    return _fallback_summary(
        number=number,
        document_date=document_date,
        name=name,
        fragment=fragment,
    )

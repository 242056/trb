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


_OFFICIAL_TITLE_RE = re.compile(
    r"^\s*(?:федеральный закон|о внесении изменен)",
    re.IGNORECASE,
)


def _clean_title(name: str | None) -> str:
    if not name:
        return ""
    title = name.strip().strip('"«»')
    title = re.sub(r"\s+", " ", title)
    return title


def looks_like_official_title(title: str | None) -> bool:
    """Официальное название поправки — не заголовок 1b (5–8 слов сути)."""
    cleaned = _clean_title(title)
    if not cleaned:
        return True
    if _OFFICIAL_TITLE_RE.search(cleaned):
        return True
    return len(cleaned.split()) > 12


def sanitize_gist_title(title: str | None) -> str:
    cleaned = _clean_title(title)
    if not cleaned or _OFFICIAL_TITLE_RE.search(cleaned):
        return ""
    words = cleaned.split()
    if len(words) > 8:
        return " ".join(words[:8])
    return cleaned


def needs_gist_refresh(*, title: str | None, summary_text: str | None) -> bool:
    """Старые сводки: официальное имя, дамп «Федеральный закон №…», больше 2 фраз."""
    from explainlaw.gates.text_checks import count_sentences

    if looks_like_official_title(title):
        return True
    text = re.sub(r"\s+", " ", (summary_text or "").strip())
    if not text or text.upper().startswith("НЕДОСТАТОЧНО ДАННЫХ"):
        return True
    if _OFFICIAL_TITLE_RE.search(text):
        return True
    if count_sentences(text) > 2:
        return True
    return len(text) > 600


def _fallback_summary(
    *, number: str | None, document_date: str | None, name: str | None, fragment: str
) -> SummaryResult:
    """Без LLM не выдумываем и не режем сырой текст — карточка уйдёт в разбор."""
    del number, document_date, name, fragment
    return SummaryResult(text="НЕДОСТАТОЧНО ДАННЫХ", title="", model_route=ModelRoute.qwen)


def _changes_context(changes: list[dict] | None) -> str:
    if not changes:
        return ""
    lines: list[str] = []
    for change in changes[:8]:
        target = change.get("target_act") or {}
        label = target.get("number") or target.get("name") or "акт"
        article = (change.get("unit_address") or {}).get("статья")
        article_part = f", ст. {article}" if article else ""
        after = re.sub(r"\s+", " ", (change.get("text_after") or "")).strip()[:400]
        lines.append(f"- {label}{article_part}: {after}" if after else f"- {label}{article_part}")
    return "Изменения (для понимания сути, не цитировать дословно):\n" + "\n".join(lines)


def generate_summary(
    *,
    number: str | None,
    document_date: str | None,
    name: str | None,
    fragment: str,
    changes: list[dict] | None = None,
) -> SummaryResult:
    from explainlaw.gates.text_checks import first_n_sentences

    context = (
        f"Номер: {number or 'не указан'}\n"
        f"Дата подписания: {document_date or 'не указана'}\n"
        f"Название: {_clean_title(name)}\n\n"
        f"{_changes_context(changes)}\n\n"
        f"Фрагмент текста закона:\n{fragment}"
    )

    from explainlaw.llm.factory import create_gateway_client, create_qwen_client

    def _from_payload(data: dict, route: ModelRoute) -> SummaryResult | None:
        summary_text = first_n_sentences(str(data.get("summary") or "").strip(), 2)
        if not summary_text:
            return None
        if summary_text.upper().startswith("НЕДОСТАТОЧНО ДАННЫХ"):
            return SummaryResult(text="НЕДОСТАТОЧНО ДАННЫХ", title="", model_route=route)
        return SummaryResult(
            text=summary_text,
            title=sanitize_gist_title(str(data.get("title") or "")),
            model_route=route,
        )

    client = create_gateway_client()
    if client.available:
        try:
            data = client.chat_json(system=_GATEWAY_SYSTEM, user=context)
            parsed = _from_payload(data, ModelRoute.gateway)
            if parsed is not None:
                return parsed
        except Exception:
            logger.exception("Gateway недоступен, пробуем Qwen на grounded контексте")

    qwen = create_qwen_client()
    if qwen.available:
        try:
            data = qwen.chat_json(system=_GATEWAY_SYSTEM, user=context)
            parsed = _from_payload(data, ModelRoute.qwen)
            if parsed is not None:
                return parsed
        except Exception:
            logger.exception("Qwen недоступен, используем механический fallback")

    return _fallback_summary(
        number=number,
        document_date=document_date,
        name=name,
        fragment=fragment,
    )

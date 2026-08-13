"""Косметическая LLM-очистка страницы OCR-текста с безопасным откатом.

Применяется ТОЛЬКО к тексту, который уже прошёл `extraction/quality.py::is_text_unreadable`
(см. `extraction/retry_ocr.py`) — никогда как последняя попытка спасти безнадёжный вход:
модель на нечитаемом фрагменте может уверенно придумать целый связный, но содержательно
неверный абзац (см. scripts/ocr_benchmark/README.md, случай 0001201602150045), и этот класс
риска не ловится сверкой критичных элементов ниже, если в исходном мусоре не было ни одного
числа/даты для сравнения — там просто нечего защищать.

Два слоя защиты, перенесённые из scripts/ocr_benchmark/llm_postprocess.py (проверены на 15
документах бенчмарка):
1. Мягкий — промпт явно перечисляет «защищённые фрагменты» страницы (критичные элементы,
   извлечённые extraction/critical_elements.py из исходного OCR) и требует сохранить их
   байт-в-байт.
2. Жёсткий — после ответа LLM критичные элементы страницы сравниваются до/после; при любом
   расхождении правка страницы целиком откатывается к исходному OCR-тексту ДО возврата.
"""

from __future__ import annotations

import logging
import re
import time

from explainlaw.extraction.critical_elements import compare_critical_elements, extract_critical_elements
from explainlaw.llm.factory import create_gateway_client, create_qwen_client

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_TEMPLATE = """Ты корректор текста, полученного OCR-распознаванием скана федерального закона.

Правь ТОЛЬКО явные артефакты распознавания в обычных словах: разорванные посередине слова,
спутанные похожие символы («0»/«О», «1»/«l»/«I», «rn»/«m» и подобные), одиночный мусор от
качества скана (обрывки символов, не образующие слов).

ЗАЩИЩЁННЫЕ ФРАГМЕНТЫ этой страницы — ниже дословные фрагменты текста (числа, даты, ссылки на
статьи/пункты/части, суммы, проценты), которые уже извлечены отдельным алгоритмом. Каждый из
них должен присутствовать в твоём ответе БАЙТ-В-БАЙТ так же, как здесь, без единого изменения —
даже если тебе кажется, что в нём ошибка OCR (дата не бьётся с соседним годом, номер статьи
выглядит нелогично, лишний/пропущенный ноль). Ты НЕ можешь надёжно понять из одной страницы,
какое значение верное — не гадай и не «исправляй» его. Если правка обычного текста рядом
случайно задевает такой фрагмент — не делай эту правку вообще, оставь всю строку как есть:
{protected_spans}

ЗАПРЕЩЕНО в любом случае, даже для фрагментов вне списка выше:
- менять числа, даты, номера статей/пунктов/частей/подпунктов, денежные суммы, проценты;
- добавлять, убирать или пересказывать смысл;
- переводить, сокращать, комментировать или оформлять markdown.

Верни ИСКЛЮЧИТЕЛЬНО исправленный текст страницы целиком, без пояснений."""

_NO_PROTECTED_SPANS = "(на этой странице защищённых фрагментов не обнаружено)"

_EMPTY_RESPONSE_ATTEMPTS = 3
_EMPTY_RESPONSE_BACKOFF_SECONDS = 4.0

# Наблюдалось в реальном ответе воркера: строка "/no_think" (управляющий тег Qwen3
# chat-template для отключения reasoning) попала в текст ответа вместо того, чтобы быть
# обработанной сервером — не критичный элемент, поэтому safety-net его не ловит.
_CONTROL_TOKEN_RE = re.compile(r"[ \t]*/(?:no_)?think\s*$")


def _strip_control_tokens(text: str) -> str:
    return _CONTROL_TOKEN_RE.sub("", text)


def _format_protected_spans(page_text: str) -> str:
    items = extract_critical_elements(page_text).all_items()
    if not items:
        return _NO_PROTECTED_SPANS
    seen: set[str] = set()
    lines: list[str] = []
    for _category, item in items:
        if item and item not in seen:
            seen.add(item)
            lines.append(f"- «{item}»")
    return "\n".join(lines) if lines else _NO_PROTECTED_SPANS


def _call_with_retries(client, *, label: str, system_prompt: str, page_text: str) -> str | None:
    """Гонит client.chat с ретраями на пустой ответ (см. модуль-докстринг llm_postprocess.py)."""
    for attempt in range(1, _EMPTY_RESPONSE_ATTEMPTS + 1):
        try:
            result = client.chat(system=system_prompt, user=page_text, temperature=0.1)
            if result:
                result = _strip_control_tokens(result)
        except Exception:
            logger.exception("%s: попытка %d/%d упала с исключением", label, attempt, _EMPTY_RESPONSE_ATTEMPTS)
            result = None

        if result and result.strip():
            return result

        logger.warning(
            "%s: попытка %d/%d вернула пустой ответ (воркер перегружен или деградировал под нагрузкой)",
            label,
            attempt,
            _EMPTY_RESPONSE_ATTEMPTS,
        )
        if attempt < _EMPTY_RESPONSE_ATTEMPTS:
            time.sleep(_EMPTY_RESPONSE_BACKOFF_SECONDS)

    return None


def clean_page_with_safety_net(ocr_text: str) -> str:
    """Возвращает пригодный текст страницы — очищенный LLM либо исходный OCR при откате.

    Никогда не бросает исключение по бизнес-логике: любой сбой LLM (недоступность, пустой
    ответ, искажение критичного элемента) молча вырождается в исходный `ocr_text`.
    """
    if not ocr_text.strip():
        return ocr_text

    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(protected_spans=_format_protected_spans(ocr_text))

    cleaned: str | None = None
    client = create_gateway_client()
    if client.available:
        cleaned = _call_with_retries(client, label="gateway", system_prompt=system_prompt, page_text=ocr_text)
    if cleaned is None:
        qwen = create_qwen_client()
        if qwen.available:
            cleaned = _call_with_retries(qwen, label="qwen", system_prompt=system_prompt, page_text=ocr_text)

    if cleaned is None:
        return ocr_text

    comparison = compare_critical_elements(ocr_text, cleaned)
    if comparison.missing:
        logger.warning("критичные элементы изменились при LLM-очистке: %s — откат к OCR", comparison.missing)
        return ocr_text

    return cleaned

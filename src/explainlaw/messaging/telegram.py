"""Отправка сообщений в Telegram (алерты и публикации)."""

from __future__ import annotations

import logging
import re
from html import escape

import httpx

from explainlaw.config import settings

logger = logging.getLogger(__name__)

_TG_MAX = 3900  # запас до лимита 4096


def telegram_configured() -> bool:
    return bool(settings.telegram_bot_token and settings.telegram_chat_id)


def send_telegram_text(text: str, *, parse_mode: str | None = "HTML") -> bool:
    """Отправить одно или несколько сообщений (нарезка по лимиту)."""
    if not telegram_configured():
        return False
    chunks = _chunk_message(text.strip(), _TG_MAX)
    if not chunks:
        return False
    ok_any = False
    for chunk in chunks:
        if _send_one(chunk, parse_mode=parse_mode):
            ok_any = True
        else:
            # fallback без HTML, если разметка сломалась
            if parse_mode and _send_one(_strip_html(chunk), parse_mode=None):
                ok_any = True
    return ok_any


def format_post_for_telegram(*, title: str, content: str) -> str:
    """Читаемый пост для группы: заголовок + тело + кликабельные ссылки."""
    body = (content or "").strip()
    # «Источник: url» → кликабельная ссылка
    body = re.sub(
        r"(?m)^Источник:\s+(https?://\S+)\s*$",
        r'🔗 <a href="\1">Источник</a>',
        escape(body),
    )
    # переносы сохраняем
    body = body.replace("\n", "\n")
    head = f"<b>{escape(title.strip())}</b>" if title else "<b>ExplainLaw</b>"
    return f"{head}\n\n{body}"


def format_alert_for_telegram(messages: list[str]) -> str:
    joined = "; ".join(messages)
    return f"⚠️ <b>ExplainLaw</b>\n{escape(joined)}"


def _send_one(text: str, *, parse_mode: str | None) -> bool:
    payload: dict = {
        "chat_id": settings.telegram_chat_id,
        "text": text[:4096],
        "disable_web_page_preview": False,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json=payload,
            timeout=20.0,
        )
        if response.status_code >= 400:
            logger.warning("Telegram API %s: %s", response.status_code, response.text[:300])
            return False
        return True
    except Exception:
        logger.exception("Не удалось отправить сообщение в Telegram")
        return False


def _chunk_message(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text] if text else []
    parts: list[str] = []
    rest = text
    while rest:
        if len(rest) <= limit:
            parts.append(rest)
            break
        cut = rest.rfind("\n\n", 0, limit)
        if cut < limit // 3:
            cut = rest.rfind("\n", 0, limit)
        if cut < limit // 3:
            cut = limit
        parts.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    return parts


def _strip_html(text: str) -> str:
    text = re.sub(r"<a href=\"([^\"]+)\">([^<]+)</a>", r"\2: \1", text)
    return re.sub(r"<[^>]+>", "", text)

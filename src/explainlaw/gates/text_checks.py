"""Общие текстовые проверки для гейтов."""

from __future__ import annotations

import re
from datetime import date, datetime

_MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)

_QUOTE_MIN_LEN = 30

_FULL_REDACTION_SOURCE_RE = re.compile(
    r"изложить\s+в\s+следующей\s+редакции",
    re.IGNORECASE,
)

_ARTICLE_IN_SOURCE_RE = re.compile(
    r"стать(?:я|ю|и|ей)\s+{article}\b",
    re.IGNORECASE,
)

_FZ_NUMBER_RE = re.compile(r"(\d+(?:-ФЗ)?)", re.IGNORECASE)

_SUMMARY_NUMBER_RE = re.compile(r"(?:№\s*)?(\d+-ФЗ)", re.IGNORECASE)
_SUMMARY_DOT_DATE_RE = re.compile(r"\d{1,2}\.\d{1,2}\.\d{4}")
_SUMMARY_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_SUMMARY_RU_DATE_RE = re.compile(
    rf"\d{{1,2}}\s+(?:{'|'.join(_MONTHS)})\s+\d{{4}}",
    re.IGNORECASE,
)


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


# Однострочные маркеры дайджеста (не тянут продолжение со следующих строк)
_STANDALONE_LINE_RE = re.compile(
    r"^(?:"
    r"\d+\.\s|"
    r"Источник:|"
    r"Изменения:|"
    r"Принят:|"
    r"Опубликован:|"
    r"Меняет:|"
    r"Еженедельный|"
    r"Вступает в силу|"
    r"🔗|"
    r"<"
    r")"
)
# Маркеры, у которых OCR часто рвёт продолжение на следующие строки
_CONTINUE_LINE_RE = re.compile(r"^•")

_QUOTE_START_RE = re.compile(r"[«\"„]")
_GUILLEMET_QUOTE_RE = re.compile(r"«([^»]{12,800})»")
_CLEAN_ARTICLE_RE = re.compile(r"^\d+(?:\.\d+)?$")
_WORDS_REPLACE_RE = re.compile(
    r"(?:заменить|дополнить)\s+словами\s*«([^»]{8,800})»",
    re.IGNORECASE,
)
# Одиночная заглавная (не самостоятельное русское слово) — типичный OCR-обрывок
_OCR_LONE_JUNK_LETTER_RE = re.compile(
    r"(?<!\S)[БГДЖЗЙЛМНПРТФХЦЧШЩЪЫЬЭЮA-HJ-Z](?!\S)"
)
# 39°7 → 39.7 (надстрочная цифра, прочитанная как degree+digit)
_OCR_DEGREE_BEFORE_DIGIT_RE = re.compile(r"(?<=\d)[°](?=\d)")
# 84¹ / 15¹ / 6¹, которые Tesseract даёт как 84? 15' 6! 8® 17° 84`
_OCR_FAKE_SUPERSCRIPT_RE = re.compile(r"(?<=\d)[®°%`?'’′!?]")
# одиночные ®°` вне цифр — почти всегда OCR-мусор в НПА
_OCR_STRAY_MARKS_RE = re.compile(r"[®°`]")
_OCR_ARTICLE_COLON_RE = re.compile(r"(?<=\d):(?=\d)")
_OCR_DENO_RE = re.compile(r"\bдено\b", re.IGNORECASE)
_OCR_JUNK_LINE_RE = re.compile(
    r"^(?:\d{1,3}|[БГДЖЗЙЛМНПРТФХЦЧШЩЪЫЬЭЮA-HJ-Z]|[®°%|]+)$"
)


def fix_ocr_artifacts(text: str) -> str:
    """Убирает типичный мусор Tesseract в текстах НПА (в т.ч. superscripts)."""
    if not text:
        return ""
    text = _OCR_DENO_RE.sub("депо", text)
    text = _OCR_ARTICLE_COLON_RE.sub(".", text)
    text = _OCR_DEGREE_BEFORE_DIGIT_RE.sub(".", text)
    text = _OCR_FAKE_SUPERSCRIPT_RE.sub("", text)
    text = _OCR_STRAY_MARKS_RE.sub("", text)
    text = _OCR_LONE_JUNK_LETTER_RE.sub(" ", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text


_SIGNATURE_TAIL_SCAN = 1500
_SIGNATURE_PRESIDENT_LOOKBACK = 600

_SIGNATURE_KREMLIN_RE = re.compile(
    r"Москва,?\s*Кремль\s*,?\s*\d{1,2}\s+(?:" + "|".join(_MONTHS) + r")\s+\d{4}\s*(?:год[а]?)?\s*№\s*\S+",
    re.IGNORECASE,
)
_SIGNATURE_PRESIDENT_RE = re.compile(
    r"Президент\S*\s+Российской\s+Федерации",
    re.IGNORECASE,
)

# Одиночная латинская буква среди кириллицы — типичный OCR-обрывок «вперемешку»
_STRAY_LATIN_LETTER_RE = re.compile(r"(?<![a-zA-Z])[a-zA-Z](?![a-zA-Z])")


def garbage_char_ratio(text: str) -> float:
    """Доля мусорных символов во фрагменте (§1.3 отчёта — гейт на долю мусора)."""
    stripped = (text or "").strip()
    if not stripped:
        return 0.0
    junk = (
        len(_OCR_STRAY_MARKS_RE.findall(stripped))
        + len(_OCR_LONE_JUNK_LETTER_RE.findall(stripped))
        + len(_STRAY_LATIN_LETTER_RE.findall(stripped))
    )
    denom = len(re.sub(r"\s", "", stripped))
    return junk / denom if denom else 0.0


def strip_signature_block(text: str) -> str:
    """Отсекает служебный блок подписи/канцелярии в конце закона (§1.3 отчёта — не ошибка
    OCR, а корректно распознанный блок, которому не место в контенте)."""
    if not text:
        return text
    tail_start = max(0, len(text) - _SIGNATURE_TAIL_SCAN)
    tail = text[tail_start:]
    match = _SIGNATURE_KREMLIN_RE.search(tail)
    if not match:
        return text
    cut_at = tail_start + match.start()
    lookback_start = max(tail_start, cut_at - _SIGNATURE_PRESIDENT_LOOKBACK)
    president_match = _SIGNATURE_PRESIDENT_RE.search(text[lookback_start:cut_at])
    if president_match:
        cut_at = lookback_start + president_match.start()
    return text[:cut_at].rstrip()


def truncate_at_word(text: str, max_len: int, *, ellipsis: str = "…") -> str:
    """Обрезка по границе слова с многоточием (без разрыва mid-word)."""
    text = (text or "").strip()
    if max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    ell = ellipsis if len(ellipsis) < max_len else ""
    budget = max_len - len(ell)
    if budget <= 0:
        return text[:max_len]
    cut = text[:budget]
    sp = max(cut.rfind(" "), cut.rfind("\n"))
    if sp >= max(1, budget // 2):
        cut = cut[:sp]
    cut = cut.rstrip(" \n\t,;:—–-")
    return f"{cut}{ell}"


_SENTENCE_END_RE = re.compile(r"[.!?]")


def truncate_at_sentence(text: str, max_len: int, *, ellipsis: str = "…") -> str:
    """Обрезка по границе предложения; при отсутствии — откат на границу слова."""
    text = (text or "").strip()
    if max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    budget_start = max(1, max_len // 2)
    cut = text[:max_len]
    last_end = None
    for match in _SENTENCE_END_RE.finditer(cut):
        last_end = match.end()
    if last_end is not None and last_end >= budget_start:
        return cut[:last_end].rstrip()
    return truncate_at_word(text, max_len, ellipsis=ellipsis)


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")


def first_n_sentences(text: str, n: int = 2) -> str:
    """Целые предложения без обрезки mid-word. Если точек нет — весь текст как одна мысль."""
    text = (text or "").strip()
    if not text or n <= 0:
        return ""
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(text) if p.strip()]
    if not parts:
        return text
    return " ".join(parts[:n])


def count_sentences(text: str) -> int:
    text = (text or "").strip()
    if not text:
        return 0
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(text) if p.strip()]
    return max(1, len(parts))


def reflow_soft_linebreaks(text: str) -> str:
    """Склеивает PDF/OCR soft-wraps; сохраняет абзацы и структурные маркеры."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?<=\w)-\n(?=\w)", "", text)

    out: list[str] = []
    current: list[str] = []
    allow_continue = False

    def flush() -> None:
        nonlocal allow_continue
        if current:
            out.append(normalize_whitespace(" ".join(current)))
            current.clear()
        allow_continue = False

    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            flush()
            if out and out[-1] != "":
                out.append("")
            continue
        # номера страниц / одиночный мусор OCR
        if _OCR_JUNK_LINE_RE.fullmatch(line):
            continue
        if _STANDALONE_LINE_RE.match(line):
            flush()
            out.append(fix_ocr_artifacts(line))
        elif _CONTINUE_LINE_RE.match(line):
            flush()
            current.append(line)
            allow_continue = True
        elif allow_continue or current:
            current.append(line)
        else:
            current.append(line)
    flush()

    cleaned: list[str] = []
    for line in out:
        if line == "" and cleaned and cleaned[-1] == "":
            continue
        cleaned.append(fix_ocr_artifacts(line) if line else line)
    return "\n".join(cleaned).strip()


def clean_quote_snippet(text: str, *, max_len: int | None = None, prefer_sentence: bool = False) -> str:
    """Текст цитаты для карточки: reflow + OCR-clean (без обрезки смысла)."""
    text = reflow_soft_linebreaks(text or "")
    match = _QUOTE_START_RE.search(text[:80])
    if match:
        text = text[match.start() :]
    text = normalize_whitespace(fix_ocr_artifacts(text))
    if max_len is not None:
        if prefer_sentence:
            return truncate_at_sentence(text, max_len)
        return truncate_at_word(text, max_len)
    return text


def sanitize_article_number(article: str | None) -> str | None:
    """Только канонический номер статьи (отсекает OCR-мусор вроде 17° / 189%)."""
    if article is None:
        return None
    token = str(article).strip().replace(",", ".")
    if _CLEAN_ARTICLE_RE.fullmatch(token):
        return token
    return None


def extract_guillemet_quotes(text: str) -> list[str]:
    return [m.group(1).strip() for m in _GUILLEMET_QUOTE_RE.finditer(text or "")]


def extract_replace_wording_quotes(text: str) -> list[str]:
    """Цитаты после «заменить/дополнить словами «...»» — типичный address_patch."""
    return [m.group(1).strip() for m in _WORDS_REPLACE_RE.finditer(text or "")]


def date_format_variants(value: date | datetime | str | None) -> list[str]:
    """Варианты даты для корпуса заземления сводки (ISO / DD.MM.YYYY / «D месяца YYYY»)."""
    if value is None:
        return []
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            if "T" in raw:
                value = datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
            else:
                value = date.fromisoformat(raw[:10])
        except ValueError:
            return [raw]

    variants = [
        value.isoformat(),
        value.strftime("%d.%m.%Y"),
        f"{value.day:02d}.{value.month:02d}.{value.year}",
        f"{value.day}.{value.month:02d}.{value.year}",
        f"{value.day}.{value.month}.{value.year}",
        f"{value.day} {_MONTHS[value.month - 1]} {value.year}",
    ]
    # без ведущего нуля в дне для DD.MM
    variants.append(f"{value.day:02d}.{value.month}.{value.year}")
    # uniq preserve order
    seen: set[str] = set()
    out: list[str] = []
    for item in variants:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def verify_quote_in_source(text_after: str | None, source_text: str) -> bool:
    if not text_after:
        return False
    sample = normalize_whitespace(reflow_soft_linebreaks(text_after)[:120])
    if len(sample) < _QUOTE_MIN_LEN:
        return False
    normalized_source = normalize_whitespace(reflow_soft_linebreaks(source_text))
    if sample in normalized_source:
        return True
    # короткие «...» из патча
    for quote in extract_guillemet_quotes(text_after):
        q = normalize_whitespace(reflow_soft_linebreaks(quote))
        if len(q) >= 12 and q in normalized_source:
            return True
    for quote in extract_replace_wording_quotes(text_after):
        q = normalize_whitespace(reflow_soft_linebreaks(quote))
        if len(q) >= 8 and q in normalized_source:
            return True
    return False


def ground_text_in_source(text_after: str | None, source_text: str) -> str | None:
    """Вернуть text_after, дословно присутствующий в источнике, либо None."""
    if not text_after or not source_text:
        return None
    cleaned = reflow_soft_linebreaks(text_after).strip()
    if not cleaned:
        return None
    if verify_quote_in_source(cleaned, source_text):
        # предпочитаем чистую цитату в кавычках, если она есть и заземлена
        for quote in extract_replace_wording_quotes(cleaned) or extract_guillemet_quotes(cleaned):
            if verify_quote_in_source(quote, source_text):
                return quote
        return cleaned

    for quote in extract_replace_wording_quotes(source_text):
        # если LLM склеил мусор — берём дословную цитату из того же фрагмента источника
        q_norm = normalize_whitespace(quote)
        c_norm = normalize_whitespace(cleaned)
        if q_norm in c_norm or c_norm[:40] in q_norm:
            return quote
    for quote in extract_guillemet_quotes(source_text):
        q_norm = normalize_whitespace(quote)
        if len(q_norm) >= 20 and normalize_whitespace(cleaned)[:40] in q_norm:
            return quote
    return None


def article_mentioned_in_source(source_text: str, article: str) -> bool:
    clean = sanitize_article_number(article)
    if clean is None:
        return False
    pattern = _ARTICLE_IN_SOURCE_RE.pattern.format(article=re.escape(clean))
    return re.search(pattern, source_text, re.IGNORECASE) is not None


def fz_number_in_source(source_text: str, number: str) -> bool:
    normalized = number.upper().replace(" ", "")
    if not normalized.endswith("-ФЗ") and normalized.isdigit():
        normalized = f"{normalized}-ФЗ"
    return normalized in source_text.upper().replace(" ", "")


def count_full_redactions_in_source(source_text: str) -> int:
    return len(_FULL_REDACTION_SOURCE_RE.findall(source_text))


def build_allowed_corpus(
    *,
    number: str | None,
    document_date: str | None,
    name: str | None,
    delta_changes: list[dict],
    publish_date: str | date | datetime | None = None,
) -> str:
    parts = [number or "", name or ""]
    parts.extend(date_format_variants(document_date))
    parts.extend(date_format_variants(publish_date))
    for change in delta_changes:
        parts.append(change.get("text_before") or "")
        parts.append(change.get("text_after") or "")
        parts.extend(date_format_variants(change.get("effective_date")))
        target = change.get("target_act") or {}
        parts.append(str(target.get("number") or ""))
        parts.extend(date_format_variants(target.get("date")))
        parts.append(str(target.get("name") or ""))
    return normalize_whitespace(" ".join(parts)).lower()


def extract_summary_numbers(summary: str) -> list[str]:
    found: list[str] = []
    for match in _SUMMARY_NUMBER_RE.findall(summary):
        token = match.upper().replace(" ", "")
        if token not in found:
            found.append(token)
    return found


def extract_summary_dates(summary: str) -> list[str]:
    dates: list[str] = []
    for regex in (_SUMMARY_DOT_DATE_RE, _SUMMARY_ISO_DATE_RE, _SUMMARY_RU_DATE_RE):
        for match in regex.findall(summary):
            token = match if isinstance(match, str) else match[0]
            if token not in dates:
                dates.append(token)
    return dates

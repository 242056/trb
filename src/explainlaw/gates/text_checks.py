"""Общие текстовые проверки для гейтов."""

from __future__ import annotations

import re

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


def verify_quote_in_source(text_after: str | None, source_text: str) -> bool:
    if not text_after or len(text_after) < _QUOTE_MIN_LEN:
        return False
    sample = normalize_whitespace(text_after[:120])
    normalized_source = normalize_whitespace(source_text)
    return sample in normalized_source


def article_mentioned_in_source(source_text: str, article: str) -> bool:
    pattern = _ARTICLE_IN_SOURCE_RE.pattern.format(article=re.escape(str(article)))
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
) -> str:
  parts = [number or "", document_date or "", name or ""]
  for change in delta_changes:
      parts.append(change.get("text_before") or "")
      parts.append(change.get("text_after") or "")
      parts.append(change.get("effective_date") or "")
      target = change.get("target_act") or {}
      parts.append(str(target.get("number") or ""))
      parts.append(str(target.get("date") or ""))
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

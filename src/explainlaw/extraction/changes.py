"""Извлечение изменений норм по статьям поправки."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from explainlaw.db.models import ApplyKind, OperationType
from explainlaw.extraction.act_identifier import parse_federal_law_references
from explainlaw.extraction.article_blocks import split_article_blocks
from explainlaw.norms.event_writer import NormChangeDraft, _regex_extract, extract_norm_changes

_AMENDS_HINT_RE = re.compile(
    r"внести|изложить|дополнить|исключить|заменить|признать|утратить",
    re.IGNORECASE,
)

_AMENDMENT_NAME_RE = re.compile(
    r"внесени\w+\s+изменени\w+",
    re.IGNORECASE,
)

# Ратификации международных протоколов — не поправки к российским ФЗ
_NON_FZ_AMENDMENT_NAME_RE = re.compile(
    r"ратификац|о\s+принятии\s+протокола",
    re.IGNORECASE,
)

_ADDRESS_PATCH_RE = re.compile(
    r"(заменить|дополнить|исключить|признать|утратить)\s+",
    re.IGNORECASE,
)

_PATCH_SNIPPET_RE = re.compile(
    r"((?:в\s+)?(?:подпункт(?:е|а)?|пункт(?:е|а)?|част(?:и|ь|ью)|стать(?:е|ю|и|я))\s+"
    r"[^.]{0,120}?(?:заменить|дополнить|исключить|признать|утратить)[^.]{0,400})",
    re.IGNORECASE | re.DOTALL,
)

# «изложить в следующей редакции» без явного «статью N» в начале
_INLINE_REDACTION_RE = re.compile(
    r"изложить\s+(?:в\s+)?(?:следующей\s+)?редакции\s*:?\s*",
    re.IGNORECASE,
)


@dataclass
class ScopedNormChange:
    """Изменение нормы с привязкой к изменяемому акту и статье поправки."""

    source_article: str
    target_act_identifier: dict[str, Any]
    draft: NormChangeDraft


def is_amendment_law(name: str | None) -> bool:
    if not name:
        return False
    if _NON_FZ_AMENDMENT_NAME_RE.search(name):
        return False
    return bool(_AMENDMENT_NAME_RE.search(name))


def target_from_document_name(name: str | None) -> dict[str, Any] | None:
    if not name:
        return None
    refs = parse_federal_law_references(name)
    if refs:
        return refs[0]
    if is_amendment_law(name):
        return {"type": "federal_law", "name": name.strip().strip('"«»')}
    return None


def _target_for_block(block: str, doc_name: str | None = None) -> dict[str, Any]:
    refs = parse_federal_law_references(block)
    if refs:
        return refs[0]
    from_name = target_from_document_name(doc_name)
    if from_name:
        return from_name
    return {"type": "federal_law", "name": "unknown"}


def _extract_patch_snippet(block: str) -> str | None:
    from explainlaw.gates.text_checks import (
        extract_replace_wording_quotes,
        ground_text_in_source,
        reflow_soft_linebreaks,
    )

    # Предпочитаем дословную цитату «заменить/дополнить словами «...»»
    wording = extract_replace_wording_quotes(block)
    if wording:
        # берём самую длинную заземлённую цитату
        best = max(wording, key=len)
        grounded = ground_text_in_source(best, block)
        if grounded:
            return grounded

    match = _PATCH_SNIPPET_RE.search(block)
    if match:
        snippet = reflow_soft_linebreaks(match.group(1).strip())
        return ground_text_in_source(snippet, block) or snippet
    if _ADDRESS_PATCH_RE.search(block):
        snippet = reflow_soft_linebreaks(block[:800].strip())
        return ground_text_in_source(snippet, block) or snippet
    redaction = _INLINE_REDACTION_RE.search(block)
    if redaction:
        snippet = reflow_soft_linebreaks(block[redaction.end() : redaction.end() + 600].strip())
        if not snippet:
            return None
        return ground_text_in_source(snippet, block) or snippet
    return None


def _unit_address_from_patch(block: str, article_num: str) -> dict[str, Any]:
    from explainlaw.gates.text_checks import sanitize_article_number

    addr: dict[str, Any] = {"статья_поправки": article_num}
    article_match = re.search(r"стать(?:ю|и|е|я)\s+(\d+(?:\.\d+)?)", block, re.IGNORECASE)
    if article_match:
        article = sanitize_article_number(article_match.group(1))
        if article:
            addr["статья"] = article
    part_match = re.search(r"част(?:и|ь|ью)\s+(\w+)", block, re.IGNORECASE)
    if part_match:
        addr["часть"] = part_match.group(1)
    return addr


def _extract_from_block(
    article_num: str,
    block: str,
    *,
    doc_name: str | None = None,
) -> list[ScopedNormChange]:
    target = _target_for_block(block, doc_name)
    results: list[ScopedNormChange] = []

    for draft in _regex_extract(block):
        results.append(
            ScopedNormChange(source_article=article_num, target_act_identifier=target, draft=draft)
        )

    if results:
        return results

    if target.get("name") == "unknown" and not _AMENDS_HINT_RE.search(block):
        return results

    # Address-patch из текста закона — до LLM (Qwen часто склеивает цитаты не дословно).
    patch = _extract_patch_snippet(block)
    if patch:
        results.append(
            ScopedNormChange(
                source_article=article_num,
                target_act_identifier=target,
                draft=NormChangeDraft(
                    unit_address=_unit_address_from_patch(block, article_num),
                    operation_type=OperationType.replace,
                    apply_kind=ApplyKind.address_patch,
                    text_after=patch,
                    effective_date=None,
                ),
            )
        )
        return results

    for draft in extract_norm_changes(block[:3000]):
        results.append(
            ScopedNormChange(
                source_article=article_num,
                target_act_identifier=target,
                draft=draft,
            )
        )

    return results


def extract_scoped_norm_changes(
    full_text: str,
    *,
    doc_name: str | None = None,
) -> list[ScopedNormChange]:
    """Извлекает изменения из всего текста, сгруппированные по статьям."""
    results: list[ScopedNormChange] = []
    for article_num, block in split_article_blocks(full_text):
        results.extend(
            _extract_from_block(article_num, block, doc_name=doc_name)
        )

    if not results and is_amendment_law(doc_name):
        target = target_from_document_name(doc_name) or {
            "type": "federal_law",
            "name": "unknown",
        }
        patch = _extract_patch_snippet(full_text)
        if patch:
            results.append(
                ScopedNormChange(
                    source_article="1",
                    target_act_identifier=target,
                    draft=NormChangeDraft(
                        unit_address={"статья_поправки": "1"},
                        operation_type=OperationType.replace,
                        apply_kind=ApplyKind.address_patch,
                        text_after=patch,
                        effective_date=None,
                    ),
                )
            )
        else:
            for draft in extract_norm_changes(full_text[:5000]):
                results.append(
                    ScopedNormChange(
                        source_article="1",
                        target_act_identifier=target,
                        draft=draft,
                    )
                )

    return results


def effective_date_for_article(
    enactments: list, article: str, default: date | None = None
) -> date | None:
    """Дата вступления для конкретной статьи поправки."""
    for item in enactments:
        addr = item.unit_address or {}
        if str(addr.get("статья")) == str(article):
            return item.effective_date
        if str(addr.get("статья_поправки")) == str(article):
            return item.effective_date
    return default

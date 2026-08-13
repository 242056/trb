"""Гейт №1 — механическая проверка дельты (§9.1) + LLM second-look (§9)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from explainlaw.config import settings
from explainlaw.db.models import DeltaCompleteness, NpaDelta, NpaDocument
from explainlaw.gates.text_checks import (
    article_mentioned_in_source,
    count_full_redactions_in_source,
    fz_number_in_source,
    garbage_char_ratio,
    sanitize_article_number,
    verify_quote_in_source,
)

logger = logging.getLogger(__name__)

_SECOND_LOOK_SYSTEM = """Ты проверяешь дельту изменений закона по исходному тексту.
Верни JSON: {"ok": true|false, "issues": ["..."]}
ok=true только если каждое изменение дельты следует из источника без выдуманных фактов."""

_GARBAGE_RATIO_THRESHOLD = 0.05


@dataclass
class FlagDraft:
    gate_number: int
    flag_type: str
    flag_details: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeltaGateResult:
    passed: bool
    flags: list[FlagDraft] = field(default_factory=list)


def _llm_second_look(source_text: str, changes: list[dict]) -> list[FlagDraft]:
    if not settings.gate_llm_verify:
        return []
    try:
        from explainlaw.llm.factory import create_qwen_client

        client = create_qwen_client()
        if not client.available:
            from explainlaw.llm.factory import create_gateway_client

            client = create_gateway_client()
        if not client.available:
            return []
        data = client.chat_json(
            system=_SECOND_LOOK_SYSTEM,
            user=(
                f"Источник (фрагмент):\n{source_text[:12000]}\n\n"
                f"Дельта:\n{json.dumps(changes, ensure_ascii=False)[:8000]}"
            ),
        )
    except Exception:
        logger.exception("LLM second-look дельты недоступен")
        return []

    if data.get("ok"):
        return []
    return [
        FlagDraft(
            gate_number=1,
            flag_type="llm_second_look_failed",
            flag_details={"issues": data.get("issues") or []},
        )
    ]


def run_delta_gate(
    doc: NpaDocument,
    source_text: str,
    delta: NpaDelta | None,
) -> DeltaGateResult:
    flags: list[FlagDraft] = []

    if delta is None:
        flags.append(
            FlagDraft(
                gate_number=1,
                flag_type="no_delta",
                flag_details={"message": "Дельта не сформирована"},
            )
        )
        return DeltaGateResult(passed=False, flags=flags)

    changes = delta.delta_data.get("changes") or []
    if not changes:
        flags.append(
            FlagDraft(
                gate_number=1,
                flag_type="empty_delta",
                flag_details={"message": "Дельта без изменений"},
            )
        )
        return DeltaGateResult(passed=False, flags=flags)

    for idx, change in enumerate(changes):
        apply_kind = change.get("apply_kind")
        unit_address = change.get("unit_address") or {}
        article = sanitize_article_number(unit_address.get("статья"))

        # OCR/LLM мусор вроде «17°» не считаем адресом статьи
        if apply_kind != "address_patch" and article:
            if not article_mentioned_in_source(source_text, article):
                flags.append(
                    FlagDraft(
                        gate_number=1,
                        flag_type="article_not_in_source",
                        flag_details={"change_index": idx, "article": article},
                    )
                )

        target = change.get("target_act") or {}
        number = target.get("number")
        if number and not fz_number_in_source(source_text, str(number)):
            flags.append(
                FlagDraft(
                    gate_number=1,
                    flag_type="fz_number_mismatch",
                    flag_details={"change_index": idx, "number": number},
                )
            )

        text_after = change.get("text_after")
        if text_after and not verify_quote_in_source(text_after, source_text):
            flags.append(
                FlagDraft(
                    gate_number=1,
                    flag_type="quote_not_verbatim",
                    flag_details={"change_index": idx, "sample": text_after[:80]},
                )
            )
        if text_after:
            ratio = garbage_char_ratio(text_after)
            if ratio > _GARBAGE_RATIO_THRESHOLD:
                flags.append(
                    FlagDraft(
                        gate_number=1,
                        flag_type="quote_garbage_ratio_high",
                        flag_details={"change_index": idx, "ratio": round(ratio, 3)},
                    )
                )

    if delta.completeness_status == DeltaCompleteness.full:
        source_count = count_full_redactions_in_source(source_text)
        delta_full_count = sum(
            1 for c in changes if c.get("apply_kind") == "full_redaction"
        )
        if source_count > delta_full_count:
            flags.append(
                FlagDraft(
                    gate_number=1,
                    flag_type="coverage_incomplete",
                    flag_details={
                        "source_full_redactions": source_count,
                        "delta_full_redactions": delta_full_count,
                    },
                )
            )

    # LLM second-look только если механика прошла (§9: сначала механика)
    if not flags:
        flags.extend(_llm_second_look(source_text, changes))

    return DeltaGateResult(passed=len(flags) == 0, flags=flags)

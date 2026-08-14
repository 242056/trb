"""Гейт №2 — заземление сводки на дельту и реквизиты (§9.2)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from explainlaw.config import settings
from explainlaw.db.models import NpaDelta, NpaDocument, NpaSummary
from explainlaw.gates.delta_gate import FlagDraft
from explainlaw.gates.text_checks import (
    build_allowed_corpus,
    count_sentences,
    extract_summary_dates,
    extract_summary_numbers,
    normalize_whitespace,
)

logger = logging.getLogger(__name__)

_VERIFY_SYSTEM = """Ты проверяющий редактор. Сверь сводку с предъявленным контекстом.
Верни JSON: {"ok": true|false, "issues": ["..."]}
ok=true только если КАЖДОЕ утверждение сводки следует из контекста без добавленных фактов."""

_INSUFFICIENT_DATA = "НЕДОСТАТОЧНО ДАННЫХ"


@dataclass
class SummaryGateResult:
    passed: bool
    flags: list[FlagDraft] = field(default_factory=list)


def _semantic_verify(summary_text: str, context: str) -> list[FlagDraft]:
    if not settings.gate_llm_verify:
        return []

    client = None
    try:
        from explainlaw.llm.factory import create_gateway_client, create_qwen_client

        # Gateway — лицо продукта; при недоступности — Qwen на grounded контексте (§8.1)
        gw = create_gateway_client()
        if gw.available:
            client = gw
        else:
            qwen = create_qwen_client()
            if qwen.available:
                client = qwen
    except Exception:
        logger.exception("Клиент семантической проверки недоступен")
        return []

    if client is None or not client.available:
        return []

    try:
        data = client.chat_json(
            system=_VERIFY_SYSTEM,
            user=f"Контекст:\n{context}\n\nСводка:\n{summary_text}",
        )
    except Exception:
        logger.exception("Семантическая проверка сводки недоступна")
        return []

    if data.get("ok"):
        return []

    return [
        FlagDraft(
            gate_number=2,
            flag_type="semantic_grounding_failed",
            flag_details={"issues": data.get("issues") or []},
        )
    ]


def run_summary_gate(
    doc: NpaDocument,
    summary: NpaSummary,
    delta: NpaDelta | None,
) -> SummaryGateResult:
    flags: list[FlagDraft] = []

    if summary.summary_text.strip().upper().startswith(_INSUFFICIENT_DATA):
        flags.append(
            FlagDraft(
                gate_number=2,
                flag_type="insufficient_data",
                flag_details={"message": "Gateway вернул НЕДОСТАТОЧНО ДАННЫХ"},
            )
        )
        return SummaryGateResult(passed=False, flags=flags)

    if count_sentences(summary.summary_text) > 2:
        flags.append(
            FlagDraft(
                gate_number=2,
                flag_type="summary_too_long",
                flag_details={"message": "Сводка длиннее двух предложений"},
            )
        )

    if delta is None:
        flags.append(
            FlagDraft(
                gate_number=2,
                flag_type="no_verified_delta",
                flag_details={"message": "Нет проверенной дельты для заземления"},
            )
        )
        return SummaryGateResult(passed=False, flags=flags)

    changes = delta.delta_data.get("changes") or []
    corpus = build_allowed_corpus(
        number=doc.number,
        document_date=doc.document_date.isoformat() if doc.document_date else None,
        name=doc.name,
        delta_changes=changes,
        publish_date=doc.publish_date_short,
    )

    for number in extract_summary_numbers(summary.summary_text):
        if number.lower() not in corpus:
            flags.append(
                FlagDraft(
                    gate_number=2,
                    flag_type="summary_number_not_grounded",
                    flag_details={"number": number},
                )
            )

    for date_token in extract_summary_dates(summary.summary_text):
        if normalize_whitespace(date_token).lower() not in corpus:
            flags.append(
                FlagDraft(
                    gate_number=2,
                    flag_type="summary_date_not_grounded",
                    flag_details={"date": date_token},
                )
            )

    # Семантика — только после механики (§9)
    if not flags:
        flags.extend(
            _semantic_verify(
                summary.summary_text,
                json.dumps(
                    {
                        "number": doc.number,
                        "document_date": (
                            doc.document_date.isoformat() if doc.document_date else None
                        ),
                        "name": doc.name,
                        "source_url": doc.source_url,
                        "delta": changes,
                    },
                    ensure_ascii=False,
                ),
            )
        )

    return SummaryGateResult(passed=len(flags) == 0, flags=flags)

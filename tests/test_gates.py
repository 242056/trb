from datetime import date

from explainlaw.db.models import DeltaCompleteness, ModelRoute, NpaDelta, NpaDocument, NpaSummary
from explainlaw.gates.delta_gate import run_delta_gate
from explainlaw.gates.summary_gate import run_summary_gate
from explainlaw.gates.text_checks import verify_quote_in_source


def _doc() -> NpaDocument:
    return NpaDocument(
        id=1,
        eo_number="0001",
        number="1-ФЗ",
        document_date=date(2026, 1, 1),
        name="Тест",
        source_url="http://example.com",
        api_metadata={},
    )


def test_verify_quote_in_source():
    source = "изложить в следующей редакции: «Новый текст статьи для проверки цитаты»"
    assert verify_quote_in_source("«Новый текст статьи для проверки цитаты»", source)


def test_delta_gate_passes_with_valid_quote():
    doc = _doc()
    source = (
        "Внести в статью 1 Федерального закона от 1 января 2020 года №10-ФЗ «Тестовый закон» "
        "следующие изменения: изложить статью 1 в следующей редакции: "
        "«Новый текст статьи достаточной длины для проверки цитаты в источнике»"
    )
    delta = NpaDelta(
        document_id=1,
        completeness_status=DeltaCompleteness.partial,
        delta_data={
            "changes": [
                {
                    "unit_address": {"статья": "1"},
                    "apply_kind": "full_redaction",
                    "target_act": {"number": "10-ФЗ", "name": "Тестовый закон"},
                    "text_after": "«Новый текст статьи достаточной длины для проверки цитаты в источнике»",
                }
            ]
        },
    )
    result = run_delta_gate(doc, source, delta)
    assert result.passed


def test_delta_gate_flags_missing_delta():
    result = run_delta_gate(_doc(), "текст", None)
    assert not result.passed
    assert result.flags[0].flag_type == "no_delta"


def test_summary_gate_grounds_numbers():
    doc = _doc()
    summary = NpaSummary(
        document_id=1,
        summary_text="Федеральный закон № 1-ФЗ от 2026-01-01 вносит изменения.",
        model_route=ModelRoute.qwen,
    )
    delta = NpaDelta(
        document_id=1,
        completeness_status=DeltaCompleteness.partial,
        delta_data={"changes": [{"target_act": {"number": "10-ФЗ"}, "text_after": "патч"}]},
    )
    result = run_summary_gate(doc, summary, delta)
    assert result.passed

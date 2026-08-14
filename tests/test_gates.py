from datetime import date

from explainlaw.db.models import (
    DeltaCompleteness,
    ModelRoute,
    NpaDelta,
    NpaDocument,
    NpaEnactment,
    NpaSummary,
    NpaText,
    TextExtractionMethod,
)
from explainlaw.gates.delta_gate import run_delta_gate
from explainlaw.gates.post_bank import _enactment_line, format_card_content
from explainlaw.gates.summary_gate import run_summary_gate
from explainlaw.gates.text_checks import garbage_char_ratio, strip_signature_block, verify_quote_in_source


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


def test_delta_gate_flags_high_garbage_ratio():
    doc = _doc()
    garbage_quote = "«a®b®c®d®e®f®g®h®i®j® мусорная цитата достаточной длины для прохождения проверки»"
    source = (
        "Внести в статью 1 Федерального закона от 1 января 2020 года №10-ФЗ «Тестовый закон» "
        "следующие изменения: изложить статью 1 в следующей редакции: " + garbage_quote
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
                    "text_after": garbage_quote,
                }
            ]
        },
    )
    assert garbage_char_ratio(garbage_quote) > 0.05
    result = run_delta_gate(doc, source, delta)
    assert not result.passed
    assert any(f.flag_type == "quote_garbage_ratio_high" for f in result.flags)


def test_format_card_content_has_new_template_fields_no_raw_quotes():
    doc = _doc()
    summary = NpaSummary(document_id=1, summary_text="Краткое содержание.")
    huge_text = "Статья 1. " + ("Много одинаковых слов подряд. " * 3000)
    delta = NpaDelta(
        document_id=1,
        completeness_status=DeltaCompleteness.full,
        delta_data={
            "changes": [
                {
                    "unit_address": {"статья": "1"},
                    "apply_kind": "full_redaction",
                    "target_act": {"number": "10-ФЗ", "name": "Тестовый закон"},
                    "text_after": huge_text,
                }
            ]
        },
    )
    assert len(huge_text) > 50000
    content = format_card_content(doc, summary, delta)

    assert "Изменения:" not in content
    assert huge_text not in content
    assert "Принят: 01.01.2026" in content
    assert "Опубликован:" in content
    assert "Вступает в силу:" in content
    assert "Меняет: Тестовый закон, ст. 1" in content
    assert "Источник: http://example.com" in content
    assert len(content) < 1000


def test_format_card_content_keeps_two_sentences_only():
    doc = _doc()
    summary = NpaSummary(
        document_id=1,
        summary_text="Первое предложение. Второе предложение. Третье лишнее.",
    )
    delta = NpaDelta(document_id=1, completeness_status=DeltaCompleteness.partial, delta_data={"changes": []})
    content = format_card_content(doc, summary, delta)
    assert "Первое предложение. Второе предложение." in content
    assert "Третье лишнее" not in content


def test_format_card_content_changes_from_document_name():
    doc = _doc()
    doc.name = 'О внесении изменения в статью 11.26 Кодекса Российской Федерации об административных правонарушениях'
    summary = NpaSummary(document_id=1, summary_text="Изменён состав нарушения.")
    delta = NpaDelta(document_id=1, completeness_status=DeltaCompleteness.partial, delta_data={"changes": []})
    content = format_card_content(doc, summary, delta)
    assert "Меняет: КоАП РФ, ст. 11.26" in content


def test_enactment_line_no_dates_no_phrase_falls_back_to_source():
    doc = _doc()
    doc.enactments = []
    doc.text = NpaText(
        document_id=1,
        full_text="Обычный текст без даты вступления в силу.",
        extraction_method=TextExtractionMethod.pdf_text,
    )
    assert _enactment_line(doc) == "см. первоисточник"


def test_enactment_line_no_dates_publication_phrase():
    doc = _doc()
    doc.enactments = []
    doc.text = NpaText(
        document_id=1,
        full_text="Настоящий Федеральный закон вступает в силу со дня его официального опубликования.",
        extraction_method=TextExtractionMethod.pdf_text,
    )
    assert _enactment_line(doc) == "со дня опубликования"


def test_enactment_line_single_date():
    doc = _doc()
    doc.enactments = [NpaEnactment(document_id=1, effective_date=date(2026, 3, 1), unit_address={})]
    assert _enactment_line(doc) == "01.03.2026"


def test_enactment_line_multiple_dates():
    doc = _doc()
    doc.enactments = [
        NpaEnactment(document_id=1, effective_date=date(2026, 3, 1), unit_address={}),
        NpaEnactment(document_id=1, effective_date=date(2026, 6, 1), unit_address={}),
    ]
    assert _enactment_line(doc) == "поэтапно, см. закон"


def test_strip_signature_block_cuts_tail_keeps_law_text():
    law_text = "Статья 1. Внести в закон следующие изменения: изложить в новой редакции."
    signed = (
        f"{law_text}\n\n"
        "Президент Российской Федерации В.Путин\n"
        "Москва, Кремль\n"
        "16 октября 2012 года №1"
    )
    result = strip_signature_block(signed)
    assert law_text in result
    assert "Президент" not in result
    assert "Кремль" not in result


def test_strip_signature_block_noop_without_signature():
    text = "Статья 1. Обычный текст закона без служебного блока подписи."
    assert strip_signature_block(text) == text


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


def test_summary_gate_flags_too_long():
    doc = _doc()
    summary = NpaSummary(
        document_id=1,
        summary_text="Первое. Второе. Третье.",
        model_route=ModelRoute.gateway,
    )
    delta = NpaDelta(
        document_id=1,
        completeness_status=DeltaCompleteness.partial,
        delta_data={"changes": [{"target_act": {"number": "10-ФЗ"}, "text_after": "патч"}]},
    )
    result = run_summary_gate(doc, summary, delta)
    assert not result.passed
    assert any(f.flag_type == "summary_too_long" for f in result.flags)
    doc = _doc()
    summary = NpaSummary(
        document_id=1,
        summary_text="НЕДОСТАТОЧНО ДАННЫХ",
        model_route=ModelRoute.gateway,
    )
    delta = NpaDelta(
        document_id=1,
        completeness_status=DeltaCompleteness.partial,
        delta_data={"changes": [{"target_act": {"number": "10-ФЗ"}, "text_after": "патч"}]},
    )
    result = run_summary_gate(doc, summary, delta)
    assert not result.passed
    assert result.flags[0].flag_type == "insufficient_data"


def test_summary_gate_flags_too_long():
    doc = _doc()
    summary = NpaSummary(
        document_id=1,
        summary_text="Первое. Второе. Третье.",
        model_route=ModelRoute.gateway,
    )
    delta = NpaDelta(
        document_id=1,
        completeness_status=DeltaCompleteness.partial,
        delta_data={"changes": [{"target_act": {"number": "10-ФЗ"}, "text_after": "патч"}]},
    )
    result = run_summary_gate(doc, summary, delta)
    assert not result.passed
    assert any(f.flag_type == "summary_too_long" for f in result.flags)

from datetime import date

from explainlaw.content.digest import _current_week_bounds, _past_week_bounds
from explainlaw.gates.text_checks import (
    clean_quote_snippet,
    fix_ocr_artifacts,
    reflow_soft_linebreaks,
    truncate_at_word,
)
from explainlaw.messaging.telegram import format_post_for_telegram


def test_past_week_bounds_monday():
    # Пн 03.08 → прошедшая неделя 27.07–02.08
    start, end = _past_week_bounds(date(2026, 8, 3))
    assert start == date(2026, 7, 27)
    assert end == date(2026, 8, 2)


def test_current_week_bounds_monday():
    start, end = _current_week_bounds(date(2026, 8, 3))
    assert start == date(2026, 8, 3)
    assert end == date(2026, 8, 9)


def test_reflow_joins_ocr_word_wraps():
    raw = (
        "«1. Сторонами\n"
        "концессионного\n"
        "соглашения,\n"
        "объектом\n"
        "которого\n"
        "являются объекты теплоснабжения"
    )
    text = reflow_soft_linebreaks(raw)
    assert "\n" not in text
    assert "Сторонами концессионного соглашения" in text


def test_reflow_keeps_digest_structure():
    raw = (
        "1. №490-ФЗ — О концессиях\n"
        "Кратко.\n\n"
        "Изменения:\n"
        "• 115-ФЗ, ст. 1: «1. Сторонами\nконцессионного\nсоглашения»\n"
        "Источник: http://example.com/doc"
    )
    text = reflow_soft_linebreaks(raw)
    assert "1. №490-ФЗ" in text
    assert "Изменения:" in text
    assert text.count("Источник:") == 1
    assert "Сторонами концессионного соглашения" in text


def test_reflow_drops_lone_ocr_letter_lines():
    raw = "на основании решения\n\nМ\n\nсуда или безвозмездно"
    text = reflow_soft_linebreaks(raw)
    assert " М " not in f" {text} "
    assert "решения" in text and "суда" in text


def test_clean_quote_strips_ocr_garbage_before_guillemet():
    raw = "|ЛИВИИ\n\n2\n«1. Сторонами\nконцессионного\nсоглашения,"
    text = clean_quote_snippet(raw, max_len=80)
    assert text.startswith("«1.")
    assert "|ЛИВИИ" not in text
    assert "Сторонами концессионного" in text


def test_fix_ocr_artifacts_common_cases():
    raw = "Статья 8®. на счете дено прав, ст. 6:7 и статьи 12! Федерального"
    text = fix_ocr_artifacts(raw)
    assert "®" not in text
    assert "дено" not in text.lower()
    assert "депо" in text
    assert "6.7" in text
    assert "12!" not in text
    assert "Статья 8." in text


def test_clean_quote_truncates_at_word_boundary():
    raw = "«" + ("слово " * 40)
    text = clean_quote_snippet(raw, max_len=50)
    assert len(text) <= 50
    assert text.endswith("…")
    assert text[:-1].rstrip().endswith("слово")


def test_truncate_at_word_short_unchanged():
    assert truncate_at_word("короткий", 20) == "короткий"


def test_telegram_format_reflows_and_keeps_html():
    text = format_post_for_telegram(
        title="Дайджест ФЗ (27.07–02.08.2026)",
        content=(
            "1. №10-ФЗ — Тест\n"
            "«1. Сторонами\nконцессионного\nсоглашения»\n"
            "Источник: http://publication.pravo.gov.ru/document/0001\n"
        ),
    )
    assert "<b>Дайджест ФЗ" in text
    assert "Сторонами концессионного соглашения" in text
    assert "\nконцессионного\n" not in text
    assert 'href="http://publication.pravo.gov.ru/document/0001"' in text

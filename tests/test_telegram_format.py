from explainlaw.messaging.telegram import (
    _chunk_message,
    format_alert_for_telegram,
    format_post_for_telegram,
)


def test_format_post_makes_source_link():
    text = format_post_for_telegram(
        title="Дайджест ФЗ (13.07–19.07.2026)",
        content=(
            "Еженедельный дайджест\n\n"
            "1. №10-ФЗ — О внесении изменений\n"
            "Кратко о сути.\n"
            "Источник: http://publication.pravo.gov.ru/document/0001\n"
        ),
    )
    assert "<b>Дайджест ФЗ" in text
    assert 'href="http://publication.pravo.gov.ru/document/0001"' in text
    assert "🔗" in text


def test_format_post_bolds_titles_and_field_labels():
    text = format_post_for_telegram(
        title="Обзор НПА · 16 августа 2026",
        content=(
            "Свежие правовые акты (16 августа 2026)\n\n"
            "1. №10-ФЗ — Штрафы для перевозчиков\n"
            "Принят: 04.08.2026\n"
            "Опубликован: 04.08.2026\n"
            "Вступает в силу: 01.09.2026\n\n"
            "Кратко о сути.\n\n"
            "Меняет: КоАП РФ, ст. 1\n"
            "Источник: http://publication.pravo.gov.ru/document/0001\n"
        ),
    )
    assert "<b>Свежие правовые акты (16 августа 2026)</b>" in text
    assert "<b>1. №10-ФЗ — Штрафы для перевозчиков</b>" in text
    assert "<b>Принят:</b> 04.08.2026" in text
    assert "<b>Опубликован:</b> 04.08.2026" in text
    assert "<b>Вступает в силу:</b> 01.09.2026" in text
    assert "<b>Меняет:</b> КоАП РФ, ст. 1" in text


def test_format_alert():
    text = format_alert_for_telegram(["Нет успешного сбора 40 ч"])
    assert "ExplainLaw" in text
    assert "Нет успешного сбора 40 ч" in text


def test_chunk_long_message():
    big = ("абзац\n\n" * 500) + "конец"
    chunks = _chunk_message(big, 200)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)
    assert "конец" in chunks[-1]

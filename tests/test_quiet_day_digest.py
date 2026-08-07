from datetime import date

from explainlaw.content.digest import (
    build_quiet_day_content,
    digest_title_for_day,
    format_ru_day,
)


def test_format_ru_day():
    assert format_ru_day(date(2026, 8, 7)) == "7 августа 2026"


def test_digest_title_for_day():
    assert digest_title_for_day(date(2026, 8, 7)) == "Обзор ФЗ · 7 августа 2026"


def test_quiet_day_content_is_readable():
    text = build_quiet_day_content(day=date(2026, 8, 7))
    assert "7 августа 2026" in text
    assert "новых федеральных законов не публиковали" in text
    assert "ошибк" not in text.lower()
    assert "нет новостей" not in text.lower()
    assert "publication.pravo.gov.ru" in text
    # Не выглядит как пустой technical ping
    assert len(text) > 120

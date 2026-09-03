from datetime import date

from explainlaw.content.digest import (
    build_quiet_day_content,
    digest_freshness_start,
    digest_title_for_day,
    format_ru_day,
)


def test_format_ru_day():
    assert format_ru_day(date(2026, 8, 7)) == "7 августа 2026"


def test_digest_title_for_day():
    assert digest_title_for_day(date(2026, 8, 7)) == "Обзор НПА · 7 августа 2026"


def test_digest_freshness_start_is_previous_monday():
    # пятница 14.08.2026 → понедельник прошедшей недели 03.08.2026
    assert digest_freshness_start(date(2026, 8, 14)) == date(2026, 8, 3)


def test_quiet_day_content_is_readable():
    text = build_quiet_day_content(day=date(2026, 8, 7))
    assert "7 августа 2026" in text
    assert "указов и постановлений" in text
    assert "ошибк" not in text.lower()
    assert "нет новостей" not in text.lower()
    assert "publication.pravo.gov.ru" in text
    # Не выглядит как пустой technical ping
    assert len(text) > 120

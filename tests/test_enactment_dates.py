from explainlaw.extraction.enactment import _parse_ru_date, extract_enactments


def test_parse_ru_date_rejects_invalid():
    assert _parse_ru_date("31", "февраля", "2020") is None
    assert _parse_ru_date("15", "января", "2020") is not None


def test_extract_enactments_skips_bad_ocr_dates():
    text = (
        "Статья 1 вступает в силу 31 февраля 2020 года. "
        "Статья 2 вступает в силу 1 марта 2020 года."
    )
    items = extract_enactments(text)
    assert all(i.effective_date.month != 2 or i.effective_date.day != 31 for i in items)
    assert any(i.unit_address.get("статья") == "2" for i in items)

from explainlaw.extraction.quality import is_text_unreadable


def test_normal_law_text_is_not_unreadable():
    text = (
        "Статья 1. Внести в Федеральный закон от 1 января 2020 года № 10-ФЗ следующие изменения: "
        "изложить статью 5 в следующей редакции: «Настоящий закон вступает в силу со дня его "
        "официального опубликования» и дополнить статью 6 частью 3 следующего содержания."
    ) * 3
    assert not is_text_unreadable(text, page_count=1)


def test_empty_text_is_unreadable():
    assert is_text_unreadable("", page_count=3)
    assert is_text_unreadable("   ", page_count=3)


def test_short_text_below_expected_length_for_page_count_is_unreadable():
    assert is_text_unreadable("короткий текст на много страниц", page_count=10)


def test_high_garbage_ratio_is_unreadable():
    text = " ".join(["a b c d e f g h i j k l m n o p"] * 20)
    assert is_text_unreadable(text, page_count=1)


def test_page_count_zero_does_not_divide_by_zero():
    assert is_text_unreadable("", page_count=0)
    assert not is_text_unreadable("х" * 500, page_count=0)

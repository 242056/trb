from explainlaw.extraction.changes import is_amendment_law


def test_is_amendment_law_positive():
    assert is_amendment_law('О внесении изменений в Федеральный закон "О банках"')


def test_is_amendment_law_excludes_ratification():
    assert not is_amendment_law("О ратификации Конвенции о...")
    assert not is_amendment_law("О принятии Протокола о...")


def test_is_amendment_law_negative():
    assert not is_amendment_law("О федеральном бюджете на 2026 год")

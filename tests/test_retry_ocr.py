import fitz

from explainlaw.extraction import retry_ocr


def _two_page_pdf_bytes() -> bytes:
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


class _FakeEngine:
    def __init__(self, pages: list[str]):
        self._pages = pages
        self._calls = 0

    def image_to_text(self, image_bytes: bytes) -> str:
        text = self._pages[self._calls]
        self._calls += 1
        return text


def test_still_unreadable_after_retry_never_calls_llm(monkeypatch):
    monkeypatch.setattr(retry_ocr, "get_ocr_engine", lambda: _FakeEngine(["", ""]))
    monkeypatch.setattr(retry_ocr, "is_text_unreadable", lambda text, page_count: True)

    def _fail_if_called(ocr_text: str) -> str:
        raise AssertionError("LLM-очистка не должна вызываться, если текст всё ещё нечитаем после retry")

    monkeypatch.setattr(retry_ocr, "clean_page_with_safety_net", _fail_if_called)

    text, still_unreadable = retry_ocr.retry_extract_with_llm_cleanup(_two_page_pdf_bytes())

    assert still_unreadable is True


def test_recovered_after_retry_applies_llm_cleanup_per_page(monkeypatch):
    monkeypatch.setattr(retry_ocr, "get_ocr_engine", lambda: _FakeEngine(["стр1 ОСR", "стр2 ОСR"]))
    monkeypatch.setattr(retry_ocr, "is_text_unreadable", lambda text, page_count: False)
    monkeypatch.setattr(retry_ocr, "clean_page_with_safety_net", lambda page_text: page_text.replace("ОСR", "OCR"))

    text, still_unreadable = retry_ocr.retry_extract_with_llm_cleanup(_two_page_pdf_bytes())

    assert still_unreadable is False
    assert "стр1 OCR" in text
    assert "стр2 OCR" in text


def test_no_ocr_engine_available_returns_unreadable_without_opening_pdf(monkeypatch):
    monkeypatch.setattr(retry_ocr, "get_ocr_engine", lambda: None)

    text, still_unreadable = retry_ocr.retry_extract_with_llm_cleanup(b"not a real pdf")

    assert still_unreadable is True
    assert text == ""

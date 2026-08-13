from dataclasses import dataclass, field

from explainlaw.extraction import llm_cleanup


@dataclass
class _FakeClient:
    available: bool
    responses: list[str | None] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)

    def chat(self, *, system: str, user: str, temperature: float) -> str | None:
        self.calls.append(user)
        return self.responses.pop(0) if self.responses else None


def test_clean_page_preserves_critical_elements(monkeypatch):
    gateway = _FakeClient(available=True, responses=["Статья 1 вступает в силу 1 января 2026 года."])
    monkeypatch.setattr(llm_cleanup, "create_gateway_client", lambda: gateway)
    monkeypatch.setattr(llm_cleanup, "create_qwen_client", lambda: _FakeClient(available=False))

    result = llm_cleanup.clean_page_with_safety_net("Статъя 1 вступает в силу 1 января 2026 года.")

    assert result == "Статья 1 вступает в силу 1 января 2026 года."


def test_clean_page_reverts_when_critical_element_altered(monkeypatch):
    ocr_text = "Статья 5 вступает в силу 1 января 2026 года."
    gateway = _FakeClient(available=True, responses=["Статья 5 вступает в силу 1 февраля 2026 года."])
    monkeypatch.setattr(llm_cleanup, "create_gateway_client", lambda: gateway)
    monkeypatch.setattr(llm_cleanup, "create_qwen_client", lambda: _FakeClient(available=False))

    result = llm_cleanup.clean_page_with_safety_net(ocr_text)

    assert result == ocr_text


def test_clean_page_falls_back_to_qwen_when_gateway_unavailable(monkeypatch):
    qwen = _FakeClient(available=True, responses=["Статья 1 вступает в силу 1 января 2026 года."])
    monkeypatch.setattr(llm_cleanup, "create_gateway_client", lambda: _FakeClient(available=False))
    monkeypatch.setattr(llm_cleanup, "create_qwen_client", lambda: qwen)

    result = llm_cleanup.clean_page_with_safety_net("Статъя 1 вступает в силу 1 января 2026 года.")

    assert result == "Статья 1 вступает в силу 1 января 2026 года."
    assert qwen.calls


def test_clean_page_strips_no_think_control_token(monkeypatch):
    gateway = _FakeClient(available=True, responses=["Статья 1 вступает в силу 1 января 2026 года. /no_think"])
    monkeypatch.setattr(llm_cleanup, "create_gateway_client", lambda: gateway)
    monkeypatch.setattr(llm_cleanup, "create_qwen_client", lambda: _FakeClient(available=False))

    result = llm_cleanup.clean_page_with_safety_net("Статъя 1 вступает в силу 1 января 2026 года.")

    assert result == "Статья 1 вступает в силу 1 января 2026 года."


def test_clean_page_returns_ocr_text_unchanged_when_blank():
    assert llm_cleanup.clean_page_with_safety_net("   ") == "   "


def test_clean_page_falls_back_to_ocr_when_no_client_returns_usable_response(monkeypatch):
    ocr_text = "Статья 1 вступает в силу 1 января 2026 года."
    gateway = _FakeClient(available=True, responses=[None, None, None])
    qwen = _FakeClient(available=True, responses=[None, None, None])
    monkeypatch.setattr(llm_cleanup, "create_gateway_client", lambda: gateway)
    monkeypatch.setattr(llm_cleanup, "create_qwen_client", lambda: qwen)
    monkeypatch.setattr(llm_cleanup, "_EMPTY_RESPONSE_BACKOFF_SECONDS", 0.0)

    result = llm_cleanup.clean_page_with_safety_net(ocr_text)

    assert result == ocr_text

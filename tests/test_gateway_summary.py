from dataclasses import dataclass

from explainlaw.db.models import ModelRoute
from explainlaw.llm import gateway


@dataclass
class _FakeClient:
    available: bool
    response: dict | None = None
    raises: bool = False

    def chat_json(self, *, system: str, user: str) -> dict:
        if self.raises:
            raise ValueError("broken json")
        return self.response or {}


def test_generate_summary_uses_gateway_json(monkeypatch):
    gateway_client = _FakeClient(available=True, response={"title": "Заголовок теста", "summary": "Меняется статья 1."})
    monkeypatch.setattr("explainlaw.llm.factory.create_gateway_client", lambda: gateway_client)
    monkeypatch.setattr("explainlaw.llm.factory.create_qwen_client", lambda: _FakeClient(available=False))

    result = gateway.generate_summary(
        number="1-ФЗ", document_date="2026-01-01", name="Тестовый закон", fragment="Статья 1. Текст."
    )
    assert result.text == "Меняется статья 1."
    assert result.title == "Заголовок теста"
    assert result.model_route == ModelRoute.gateway


def test_generate_summary_falls_back_to_qwen_when_gateway_unavailable(monkeypatch):
    monkeypatch.setattr("explainlaw.llm.factory.create_gateway_client", lambda: _FakeClient(available=False))
    qwen_client = _FakeClient(available=True, response={"title": "Заголовок от Qwen", "summary": "Кратко о законе."})
    monkeypatch.setattr("explainlaw.llm.factory.create_qwen_client", lambda: qwen_client)

    result = gateway.generate_summary(
        number="1-ФЗ", document_date="2026-01-01", name="Тестовый закон", fragment="Статья 1. Текст."
    )
    assert result.text == "Кратко о законе."
    assert result.title == "Заголовок от Qwen"
    assert result.model_route == ModelRoute.qwen


def test_generate_summary_mechanical_fallback_on_broken_json(monkeypatch):
    monkeypatch.setattr(
        "explainlaw.llm.factory.create_gateway_client", lambda: _FakeClient(available=True, raises=True)
    )
    monkeypatch.setattr(
        "explainlaw.llm.factory.create_qwen_client", lambda: _FakeClient(available=True, raises=True)
    )

    result = gateway.generate_summary(
        number="1-ФЗ",
        document_date="2026-01-01",
        name="Тестовый закон",
        fragment="Статья 1. Текст закона для проверки.",
    )
    assert result.model_route == ModelRoute.qwen
    assert "Тестовый закон" in result.text
    assert result.title == "Тестовый закон"


def test_generate_summary_mechanical_fallback_when_no_clients_available(monkeypatch):
    monkeypatch.setattr("explainlaw.llm.factory.create_gateway_client", lambda: _FakeClient(available=False))
    monkeypatch.setattr("explainlaw.llm.factory.create_qwen_client", lambda: _FakeClient(available=False))

    result = gateway.generate_summary(
        number=None, document_date=None, name=None, fragment="Просто фрагмент текста без реквизитов."
    )
    assert result.model_route == ModelRoute.qwen
    assert result.title == ""
    assert "Просто фрагмент текста" in result.text

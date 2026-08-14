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
    assert result.text == "НЕДОСТАТОЧНО ДАННЫХ"
    assert result.title == ""


def test_generate_summary_mechanical_fallback_when_no_clients_available(monkeypatch):
    monkeypatch.setattr("explainlaw.llm.factory.create_gateway_client", lambda: _FakeClient(available=False))
    monkeypatch.setattr("explainlaw.llm.factory.create_qwen_client", lambda: _FakeClient(available=False))

    result = gateway.generate_summary(
        number=None, document_date=None, name=None, fragment="Просто фрагмент текста без реквизитов."
    )
    assert result.model_route == ModelRoute.qwen
    assert result.title == ""
    assert result.text == "НЕДОСТАТОЧНО ДАННЫХ"


def test_sanitize_gist_title_strips_official_name():
    assert gateway.sanitize_gist_title("О внесении изменений в КоАП РФ") == ""
    assert gateway.sanitize_gist_title("Федеральный закон № 10-ФЗ О таможенном регулировании") == ""
    assert gateway.sanitize_gist_title("Новые штрафы для перевозчиков") == "Новые штрафы для перевозчиков"
    assert gateway.sanitize_gist_title("Один два три четыре пять шесть семь восемь девять") == (
        "Один два три четыре пять шесть семь восемь"
    )


def test_needs_gist_refresh_detects_old_official_copy():
    assert gateway.needs_gist_refresh(
        title="О внесении изменений в статью 11.26 КоАП РФ",
        summary_text="Федеральный закон № 10-ФЗ о внесении изменений.",
    )
    assert not gateway.needs_gist_refresh(
        title="Штрафы за перевозку пассажиров",
        summary_text="Для перевозчиков вырос штраф. Касается водителей автобусов.",
    )


def test_generate_summary_strips_official_title_and_clips_sentences(monkeypatch):
    gateway_client = _FakeClient(
        available=True,
        response={
            "title": "О внесении изменений в КоАП",
            "summary": "Первое. Второе. Третье лишнее.",
        },
    )
    monkeypatch.setattr("explainlaw.llm.factory.create_gateway_client", lambda: gateway_client)
    monkeypatch.setattr("explainlaw.llm.factory.create_qwen_client", lambda: _FakeClient(available=False))

    result = gateway.generate_summary(
        number="1-ФЗ", document_date="2026-01-01", name="Тестовый закон", fragment="Статья 1. Текст."
    )
    assert result.title == ""
    assert result.text == "Первое. Второе."

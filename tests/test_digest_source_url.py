from types import SimpleNamespace

from explainlaw.content.digest import build_digest_content
from explainlaw.content.scoring import ScoredCard


def test_digest_includes_source_url():
    doc = SimpleNamespace(
        number="10-ФЗ",
        name="О внесении изменений",
        eo_number="0001202601010001",
        source_url="http://publication.pravo.gov.ru/document/0001202601010001",
    )
    scored = ScoredCard(
        document_id=1,
        document=doc,  # type: ignore[arg-type]
        delta=None,
        title="№10-ФЗ — Кратко о законе",
        content="Кратко: меняется статья 1.",
        score=1.0,
    )
    text = build_digest_content([scored], week_label="2026-07-13 — 2026-07-19")
    assert "Источник: http://publication.pravo.gov.ru/document/0001202601010001" in text
    assert "№10-ФЗ" in text

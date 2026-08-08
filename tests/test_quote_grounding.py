"""Заземление цитат дельты на исходный текст закона."""

from datetime import date

from explainlaw.gates.text_checks import (
    build_allowed_corpus,
    date_format_variants,
    ground_text_in_source,
    sanitize_article_number,
    verify_quote_in_source,
)
from explainlaw.norms.event_writer import NormChangeDraft, _ground_draft
from explainlaw.db.models import ApplyKind, OperationType


def test_verify_quote_accepts_replace_wording():
    source = (
        "слова «архив кинофотодокументов» заменить словами "
        "«Российский государственный архив кинофотофонодокументов», "
        "дополнить словами «и фонопродукции»"
    )
    bad = (
        "Российский государственный архив кинофотофонодокументов, "
        "фотодокументам и фонодо"
    )
    assert not verify_quote_in_source(bad, source)
    grounded = ground_text_in_source(bad, source)
    assert grounded == "Российский государственный архив кинофотофонодокументов"
    assert verify_quote_in_source(grounded, source)


def test_sanitize_article_rejects_ocr_noise():
    assert sanitize_article_number("17") == "17"
    assert sanitize_article_number("17.1") == "17.1"
    assert sanitize_article_number("17°") is None
    assert sanitize_article_number("189%") is None


def test_publish_date_in_summary_corpus():
    corpus = build_allowed_corpus(
        number="10-ФЗ",
        document_date="2026-08-04",
        name="Тест",
        delta_changes=[],
        publish_date=date(2026, 8, 4),
    )
    assert "04.08.2026" in corpus
    assert "4 августа 2026" in corpus


def test_date_format_variants_cover_summary_tokens():
    variants = {v.lower() for v in date_format_variants(date(2026, 8, 4))}
    assert "2026-08-04" in variants
    assert "04.08.2026" in variants
    assert "4 августа 2026" in variants


def test_ground_draft_drops_ungrounded_full_redaction():
    fragment = "заменить словами «короткая цитата из закона достаточной длины»"
    draft = NormChangeDraft(
        unit_address={"статья": "1"},
        operation_type=OperationType.full_redaction,
        apply_kind=ApplyKind.full_redaction,
        text_after="выдуманный текст которого нет в источнике совсем",
        effective_date=None,
    )
    assert _ground_draft(draft, fragment) is None

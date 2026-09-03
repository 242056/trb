from datetime import date
from unittest.mock import MagicMock

from explainlaw.db.models import NpaDocument, NpaRaw, NpaSummary, NpaText, RawFileType, TextExtractionMethod
from explainlaw.extraction.pdf_extractor import ExtractionResult
from explainlaw.pipeline import processor as processor_module
from explainlaw.pipeline.processor import DocumentProcessor


def _doc() -> NpaDocument:
    doc = NpaDocument(
        id=1,
        eo_number="0001202001010001",
        number="1-ФЗ",
        document_date=date(2026, 1, 1),
        name="Тест",
        source_url="http://example.com",
        api_metadata={},
    )
    doc.raw_files = [NpaRaw(id=1, document_id=1, raw_type=RawFileType.pdf, storage_path="raw/0001.pdf")]
    doc.text = None
    doc.enactments = []
    doc.relations_out = []
    doc.delta = None
    # Непусто -> generate_summary не вызывается, поэтому LLM-клиенты сводки не нужны в этих тестах.
    doc.summaries = [NpaSummary(id=1, document_id=1, summary_text="старая сводка")]
    return doc


def _make_processor(monkeypatch, *, retry_result):
    session = MagicMock()
    storage = MagicMock()
    storage.get_by_path.return_value = b"%PDF-1.4 fake"
    pravo = MagicMock()
    pravo.download_pdf.return_value = b"%PDF-1.4 fresh"

    # Изолируем блок извлечения текста от остального конвейера (дельта/сводка/сектора уже
    # покрыты своими тестами) — здесь важна только логика retry-и-drop.
    monkeypatch.setattr(processor_module, "extract_enactments", lambda *a, **k: [])
    monkeypatch.setattr(processor_module, "extract_relations", lambda *a, **k: [])
    monkeypatch.setattr(processor_module, "extract_scoped_norm_changes", lambda *a, **k: [])
    monkeypatch.setattr(processor_module, "build_delta_for_document", lambda *a, **k: None)
    monkeypatch.setattr(processor_module, "assign_sectors", lambda *a, **k: 0)
    monkeypatch.setattr(processor_module, "assign_act_group", lambda *a, **k: None)
    monkeypatch.setattr(processor_module, "enqueue_from_relations", lambda *a, **k: 0)
    monkeypatch.setattr(processor_module, "retry_extract_with_llm_cleanup", lambda pdf_bytes: retry_result)

    proc = DocumentProcessor(session, storage, pravo=pravo)
    return proc, session, storage, pravo


def _added_texts(session) -> list[NpaText]:
    return [c.args[0] for c in session.add.call_args_list if isinstance(c.args[0], NpaText)]


def test_readable_first_try_skips_retry_entirely(monkeypatch):
    doc = _doc()
    proc, session, storage, pravo = _make_processor(monkeypatch, retry_result=("не должно вызваться", False))
    monkeypatch.setattr(
        processor_module,
        "extract_text_from_pdf",
        lambda pdf_bytes: ExtractionResult(
            text="нормальный читаемый текст закона", method=TextExtractionMethod.pdf_text, page_count=1
        ),
    )
    monkeypatch.setattr(processor_module, "is_text_unreadable", lambda text, page_count: False)

    result = proc._process_document(doc)

    pravo.download_pdf.assert_not_called()
    assert result["text_extracted"] is True
    assert _added_texts(session)[-1].full_text == "нормальный читаемый текст закона"


def test_unreadable_first_try_recovers_after_retry(monkeypatch):
    doc = _doc()
    proc, session, storage, pravo = _make_processor(
        monkeypatch, retry_result=("текст после переOCR и LLM-очистки, читаемый", False)
    )
    monkeypatch.setattr(
        processor_module,
        "extract_text_from_pdf",
        lambda pdf_bytes: ExtractionResult(text="мус ор", method=TextExtractionMethod.ocr, page_count=1),
    )
    monkeypatch.setattr(processor_module, "is_text_unreadable", lambda text, page_count: text == "мус ор")

    result = proc._process_document(doc)

    pravo.download_pdf.assert_called_once_with(doc.eo_number)
    assert result["text_extracted"] is True
    added = _added_texts(session)
    assert added[-1].full_text == "текст после переOCR и LLM-очистки, читаемый"
    assert added[-1].extraction_method == TextExtractionMethod.ocr
    # is_unreadable не выставлен явно (в отличие от excluded-ветки) — на неперсистентном
    # объекте это остаётся None до записи в БД, где server_default=false() применит False.
    assert not added[-1].is_unreadable


def test_unreadable_after_retry_is_excluded_before_any_llm_call(monkeypatch):
    doc = _doc()
    proc, session, storage, pravo = _make_processor(monkeypatch, retry_result=("всё равно мусор", True))
    monkeypatch.setattr(
        processor_module,
        "extract_text_from_pdf",
        lambda pdf_bytes: ExtractionResult(text="мус ор", method=TextExtractionMethod.ocr, page_count=1),
    )
    monkeypatch.setattr(processor_module, "is_text_unreadable", lambda text, page_count: True)

    result = proc._process_document(doc)

    assert result == {"excluded_unreadable": True}
    pravo.download_pdf.assert_called_once_with(doc.eo_number)
    added = _added_texts(session)
    assert len(added) == 1
    assert added[0].is_unreadable is True
    assert added[0].full_text == "всё равно мусор"
    session.commit.assert_called_once()


def test_pending_documents_default_branch_excludes_permanently_unreadable(monkeypatch):
    session = MagicMock()
    session.execute.return_value.scalars.return_value.all.return_value = []
    proc = DocumentProcessor(session, MagicMock(), pravo=MagicMock())

    proc._pending_documents(limit=None)

    stmt = session.execute.call_args.args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "is_unreadable" in compiled


def test_missing_pdf_error_detection():
    assert processor_module._is_missing_pdf_error(ValueError("PDF не найден в сырье"))
    assert processor_module._is_missing_pdf_error(
        RuntimeError("S3 operation failed; code: NoSuchKey, message: The specified key does not exist.")
    )
    assert not processor_module._is_missing_pdf_error(ValueError("текст слишком короткий"))


def test_process_batch_marks_missing_pdf_and_continues(monkeypatch):
    doc = _doc()
    session = MagicMock()
    storage = MagicMock()
    storage.get_by_path.side_effect = RuntimeError(
        "S3 operation failed; code: NoSuchKey, message: The specified key does not exist."
    )
    proc = DocumentProcessor(session, storage, pravo=MagicMock())
    monkeypatch.setattr(proc, "_pending_documents", lambda limit: [doc])
    monkeypatch.setattr(processor_module, "extract_enactments", lambda *a, **k: [])
    monkeypatch.setattr(processor_module, "extract_relations", lambda *a, **k: [])
    monkeypatch.setattr(processor_module, "extract_scoped_norm_changes", lambda *a, **k: [])
    monkeypatch.setattr(processor_module, "build_delta_for_document", lambda *a, **k: None)
    monkeypatch.setattr(processor_module, "assign_sectors", lambda *a, **k: 0)
    monkeypatch.setattr(processor_module, "assign_act_group", lambda *a, **k: None)
    monkeypatch.setattr(processor_module, "enqueue_from_relations", lambda *a, **k: 0)
    monkeypatch.setattr(
        processor_module,
        "extract_text_from_pdf",
        lambda pdf_bytes: ExtractionResult(text="x", method=TextExtractionMethod.pdf_text, page_count=1),
    )

    stats = proc._process_batch(limit=10)

    assert stats.candidates == 1
    assert stats.excluded_missing_pdf == 1
    assert stats.errors == 0
    assert stats.text_extracted == 0
    added = _added_texts(session)
    assert len(added) == 1
    assert added[0].is_unreadable is True


def test_process_unlimited_runs_batches_until_empty(monkeypatch):
    session = MagicMock()
    proc = DocumentProcessor(session, MagicMock(), pravo=MagicMock())
    calls = {"n": 0}

    def fake_batch(*, limit):
        calls["n"] += 1
        if calls["n"] == 1:
            s = processor_module.ProcessStats(candidates=2, text_extracted=2, summarized=2)
            return s
        return processor_module.ProcessStats(candidates=0)

    monkeypatch.setattr(proc, "_process_batch", fake_batch)
    stats = proc.process(limit=None)
    assert calls["n"] == 2
    assert stats.candidates == 2
    assert stats.text_extracted == 2
    assert stats.summarized == 2

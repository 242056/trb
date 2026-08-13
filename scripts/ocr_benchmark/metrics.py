"""CER/WER + мусор/подписи-метрики для ручного OCR-бенчмарка (§4 плана).

Три раздельные метрики, намеренно не объединяются в одно число (см. explainlaw_fix_report_v1.md
§1.1): CER/WER на полном тексте, точность критичных элементов (critical_elements.py) и доля
служебного мусора/подписей — последняя явно помечена как proxy, не gate.
"""

from __future__ import annotations

from dataclasses import dataclass

import jiwer

from explainlaw.gates.text_checks import (
    fix_ocr_artifacts,
    garbage_char_ratio,
    normalize_whitespace,
    reflow_soft_linebreaks,
    strip_signature_block,
)


def _prepare(text: str) -> str:
    """reflow + normalize — общая подготовка перед CER/WER, чтобы мягкие переносы строк
    не раздували ошибку по причинам, не связанным с качеством распознавания (см. план §4.1)."""
    return normalize_whitespace(reflow_soft_linebreaks(text or ""))


@dataclass
class CerWerResult:
    cer_raw: float
    wer_raw: float
    cer_fixed: float
    wer_fixed: float


def compute_cer_wer(reference_text: str, hypothesis_text: str) -> CerWerResult:
    """reference — вычитанный эталон (.reviewed.txt, подпись НЕ вырезана, см. план §4.1).
    hypothesis — сырой вывод движка (.raw.txt, тоже с подписью)."""
    reference = _prepare(reference_text)
    hypothesis_raw = _prepare(hypothesis_text)
    hypothesis_fixed = _prepare(fix_ocr_artifacts(hypothesis_text or ""))

    if not reference:
        return CerWerResult(cer_raw=0.0, wer_raw=0.0, cer_fixed=0.0, wer_fixed=0.0)

    return CerWerResult(
        cer_raw=jiwer.cer(reference, hypothesis_raw),
        wer_raw=jiwer.wer(reference, hypothesis_raw),
        cer_fixed=jiwer.cer(reference, hypothesis_fixed),
        wer_fixed=jiwer.wer(reference, hypothesis_fixed),
    )


@dataclass
class GarbageResult:
    garbage_ratio: float
    signature_share: float


def compute_garbage_metrics(text: str) -> GarbageResult:
    """Два дополняющих proxy на тексте с сохранённой подписью + fix_ocr_artifacts (§4.3).
    Не точная метрика — strip_signature_block ловит только один паттерн конца документа,
    не внутристраничные штампы/печати; поэтому это proxy для визуальной оценки, не gate."""
    fixed = fix_ocr_artifacts(text or "")
    ratio = garbage_char_ratio(fixed)

    stripped = strip_signature_block(fixed)
    signature_share = (len(fixed) - len(stripped)) / len(fixed) if fixed else 0.0

    return GarbageResult(garbage_ratio=ratio, signature_share=signature_share)


@dataclass
class CorpusAggregate:
    """Агрегация по корпусу целиком: суммарное расстояние редактирования / суммарная длина
    эталона — не среднее по документам (короткие и длинные документы иначе весят по-разному)."""

    cer_corpus: float
    wer_corpus: float


def aggregate_corpus_cer_wer(pairs: list[tuple[str, str]]) -> CorpusAggregate:
    """pairs — список (reference_text, hypothesis_text) уже без fix_ocr_artifacts (raw-вариант);
    для fixed-варианта вызывающий код передаёт hypothesis уже прогнанный через fix_ocr_artifacts."""
    references = [_prepare(ref) for ref, _ in pairs]
    hypotheses = [_prepare(hyp) for _, hyp in pairs]
    references = [r for r in references if r]
    hypotheses = hypotheses[: len(references)]
    if not references:
        return CorpusAggregate(cer_corpus=0.0, wer_corpus=0.0)
    return CorpusAggregate(
        cer_corpus=jiwer.cer(references, hypotheses),
        wer_corpus=jiwer.wer(references, hypotheses),
    )

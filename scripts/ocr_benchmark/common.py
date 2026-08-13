"""Общие пути, датаклассы и хелперы для ручного OCR-бенчмарка (Приоритет 1.1)."""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass, fields
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

# explainlaw.config.Settings резолвит `.env` относительно текущей рабочей директории процесса
# (SettingsConfigDict(env_file=".env")), а не относительно расположения config.py. Скрипты этого
# бенчмарка по README запускаются через `cd scripts/ocr_benchmark && python ...` — без явной
# загрузки здесь Settings молча получает пустые/дефолтные значения (LLM_TRANSPORT, ключи и т.п.),
# и любой код, зависящий от них (например create_qwen_client()), работает не так, как в проде.
load_dotenv(ROOT / ".env")

BENCH_DIR = Path(__file__).resolve().parent
DATA_DIR = BENCH_DIR / "data"
PDF_DIR = DATA_DIR / "pdf"
OCR_DIR = DATA_DIR / "ocr"
GROUND_TRUTH_DIR = DATA_DIR / "ground_truth"

CANDIDATE_POOL_CSV = DATA_DIR / "candidate_pool.csv"
SAMPLE_MANIFEST_CSV = BENCH_DIR / "sample_manifest.csv"
REPORT_MD = BENCH_DIR / "report.md"
RAW_METRICS_CSV = BENCH_DIR / "raw_metrics.csv"

ENGINE_NAMES = ("tesseract", "paddle", "pymupdf", "tesseract+llm")
DRAFT_ENGINE_DEFAULT = "tesseract"

SAMPLE_FIELDNAMES = (
    "eo_number",
    "number",
    "document_date",
    "pages_count",
    "extraction_method",
    "pdf_storage_path",
    "era_bucket",
    "length_bucket",
    "has_tables",
    "scan_quality",
    "include",
    "notes",
)


def era_bucket(document_date: date | None) -> str:
    if document_date is None:
        return "unknown"
    if document_date.year <= 2015:
        return "<=2015"
    if document_date.year <= 2019:
        return "2016-2019"
    return "2020+"


def length_bucket(pages_count: int | None) -> str:
    if pages_count is None:
        return "unknown"
    if pages_count <= 3:
        return "short(<=3)"
    if pages_count <= 30:
        return "medium(4-30)"
    if pages_count <= 300:
        return "long(31-300)"
    return "extreme(>300)"


@dataclass
class SampleCandidate:
    eo_number: str
    number: str
    document_date: str
    pages_count: int
    extraction_method: str
    pdf_storage_path: str
    era_bucket: str
    length_bucket: str
    has_tables: str = ""
    scan_quality: str = ""
    include: str = ""
    notes: str = ""

    def to_row(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_row(cls, row: dict) -> "SampleCandidate":
        known = {f.name for f in fields(cls)}
        return cls(**{k: (row.get(k) or "") for k in known if k != "pages_count"}, pages_count=int(row["pages_count"] or 0))

    @property
    def included(self) -> bool:
        return self.include.strip().lower() in {"1", "true", "yes", "да", "y"}


def write_candidates_csv(path: Path, candidates: list[SampleCandidate]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=SAMPLE_FIELDNAMES)
        writer.writeheader()
        for candidate in candidates:
            writer.writerow(candidate.to_row())


def read_manifest(path: Path = SAMPLE_MANIFEST_CSV) -> list[SampleCandidate]:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} не найден — сначала сформируйте выборку (select_sample.py) "
            "и сохраните вручную размеченный файл как sample_manifest.csv"
        )
    with path.open("r", encoding="utf-8", newline="") as fh:
        return [SampleCandidate.from_row(row) for row in csv.DictReader(fh)]


def included_manifest(path: Path = SAMPLE_MANIFEST_CSV) -> list[SampleCandidate]:
    return [c for c in read_manifest(path) if c.included]


def pdf_cache_path(eo_number: str) -> Path:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    return PDF_DIR / f"{eo_number}.pdf"


def fetch_pdf_bytes(storage, candidate: SampleCandidate) -> bytes:
    """Скачивает PDF в локальный кэш (для ручного просмотра и повторных прогонов) и возвращает байты."""
    cache_path = pdf_cache_path(candidate.eo_number)
    if cache_path.exists():
        return cache_path.read_bytes()
    data = storage.get_by_path(candidate.pdf_storage_path)
    cache_path.write_bytes(data)
    return data


def ocr_engine_dir(eo_number: str) -> Path:
    path = OCR_DIR / eo_number
    path.mkdir(parents=True, exist_ok=True)
    return path


def ocr_raw_path(eo_number: str, engine: str) -> Path:
    return ocr_engine_dir(eo_number) / f"{engine}.raw.txt"


def ocr_cleaned_path(eo_number: str, engine: str) -> Path:
    return ocr_engine_dir(eo_number) / f"{engine}.cleaned.txt"


def ocr_altered_critical_path(eo_number: str, engine: str) -> Path:
    """Флаг-файл: хотя бы на одной странице LLM попыталась изменить критичный элемент.

    С безопасным откатом (см. llm_postprocess.py) это больше не означает, что изменение дошло
    до финального текста — страница откатывается к OCR-варианту до того, как попадёт в
    `<engine>.raw.txt`. Флаг остаётся диагностическим сигналом «промпт сам по себе не удержал
    ограничение на этой странице», отдельно от `ocr_llm_reverted_pages_path` (сколько страниц
    физически откачено).
    """
    return ocr_engine_dir(eo_number) / f"{engine}.altered_critical.flag"


def ocr_llm_reverted_pages_path(eo_number: str, engine: str) -> Path:
    """Диагностика: число страниц документа, чья LLM-правка была отклонена и откачена к OCR."""
    return ocr_engine_dir(eo_number) / f"{engine}.reverted_pages.txt"


def ground_truth_draft_path(eo_number: str) -> Path:
    GROUND_TRUTH_DIR.mkdir(parents=True, exist_ok=True)
    return GROUND_TRUTH_DIR / f"{eo_number}.draft.txt"


def ground_truth_reviewed_path(eo_number: str) -> Path:
    GROUND_TRUTH_DIR.mkdir(parents=True, exist_ok=True)
    return GROUND_TRUTH_DIR / f"{eo_number}.reviewed.txt"

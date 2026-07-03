import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

import httpx
from confluent_kafka import Producer
from sqlalchemy.orm import Session

from explainlaw.collector.refs import sync_reference_data
from explainlaw.collector.repository import DocumentRepository
from explainlaw.config import settings
from explainlaw.db.models import RawFileType
from explainlaw.pipeline.topics import TOPIC_DOCUMENT_DISCOVERED, TOPIC_RAW_STORED
from explainlaw.pravo.client import PravoApiClient
from explainlaw.pravo.models import PravoDocumentItem
from explainlaw.storage.object_store import ObjectStorage

logger = logging.getLogger(__name__)


@dataclass
class CollectStats:
    fetched: int = 0
    new: int = 0
    skipped: int = 0
    no_pdf: int = 0
    errors: int = 0
    error_details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "fetched": self.fetched,
            "new": self.new,
            "skipped": self.skipped,
            "no_pdf": self.no_pdf,
            "errors": self.errors,
            "error_details": self.error_details,
        }


class DailyCollector:
    """Ежедневный сбор ФЗ: API → дедуп по eoNumber → сырьё в MinIO → БД."""

    def __init__(
        self,
        session: Session,
        storage: ObjectStorage,
        *,
        pravo: PravoApiClient | None = None,
        kafka_producer: Producer | None = None,
    ) -> None:
        self._session = session
        self._storage = storage
        self._pravo = pravo or PravoApiClient()
        self._repo = DocumentRepository(session, storage)
        self._owns_pravo = pravo is None
        self._kafka = kafka_producer

    def close(self) -> None:
        if self._owns_pravo:
            self._pravo.close()

    def collect(
        self,
        *,
        target_date: date | None = None,
        period_type: str = "daily",
        date_from: date | None = None,
        date_to: date | None = None,
        all_catalog: bool = False,
    ) -> CollectStats:
        if all_catalog:
            return self._collect_catalog(date_from=date_from, date_to=date_to)

        if date_from or date_to:
            return self._collect_range(
                date_from or date_to or date.today(),
                date_to or date.today(),
            )

        stats = CollectStats()
        sync_reference_data(self._session, self._pravo)
        fz_type_id = self._pravo.resolve_fz_type_id()

        for item in self._pravo.iter_federal_laws(
            period_type=period_type if target_date is None else "day",
            target_date=target_date,
            fz_type_id=fz_type_id,
        ):
            self._ingest_or_skip(item, stats)

        self._session.commit()
        return stats

    def _collect_catalog(
        self,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> CollectStats:
        """Сбор всего каталога ФЗ из API (§3 ТЗ) — публикации president, не бэкофилл изменяемых актов (§8.3)."""
        stats = CollectStats()
        sync_reference_data(self._session, self._pravo)
        fz_type_id = self._pravo.resolve_fz_type_id()

        logger.info(
            "Полный каталог API: ~%d ФЗ (официальный источник, данные с ~2011 года)",
            settings.pravo_catalog_fz_total,
        )

        for item in self._pravo.iter_all_federal_laws(
            fz_type_id=fz_type_id,
            publish_date_from=date_from,
            publish_date_to=date_to,
        ):
            self._ingest_or_skip(item, stats)

        self._session.commit()
        return stats

    def _collect_range(self, date_from: date, date_to: date) -> CollectStats:
        if date_from > date_to:
            date_from, date_to = date_to, date_from

        stats = CollectStats()
        sync_reference_data(self._session, self._pravo)
        fz_type_id = self._pravo.resolve_fz_type_id()

        current = date_from
        while current <= date_to:
            logger.info("Сбор ФЗ за %s", current.isoformat())
            for item in self._pravo.iter_federal_laws(
                period_type="day",
                target_date=current,
                fz_type_id=fz_type_id,
            ):
                self._ingest_or_skip(item, stats)
            current += timedelta(days=1)

        self._session.commit()
        return stats

    def ingest_one(self, item: PravoDocumentItem) -> bool:
        """Сохраняет один документ из API. Возвращает True если новый."""
        if self._repo.exists(item.eo_number):
            return False
        self._ingest_item(item)
        self._session.commit()
        return True

    def _ingest_or_skip(self, item: PravoDocumentItem, stats: CollectStats) -> None:
        stats.fetched += 1
        if self._repo.exists(item.eo_number):
            stats.skipped += 1
            if stats.skipped % 500 == 0:
                logger.info("Пропущено (уже в базе): %d, новых: %d", stats.skipped, stats.new)
            return
        try:
            has_pdf = self._ingest_item(item)
            stats.new += 1
            if not has_pdf:
                stats.no_pdf += 1
            self._session.commit()
            if has_pdf:
                logger.info("Сохранён новый ФЗ: %s — %s", item.eo_number, item.name)
            else:
                logger.info(
                    "Сохранён новый ФЗ без PDF (метаданные): %s — %s",
                    item.eo_number,
                    item.name,
                )
        except Exception as exc:
            stats.errors += 1
            msg = f"{item.eo_number}: {exc}"
            stats.error_details.append(msg)
            logger.exception("Ошибка при сохранении %s", item.eo_number)
            self._session.rollback()

    def _ingest_item(self, item: PravoDocumentItem) -> bool:
        """Сохраняет документ. Возвращает True, если PDF тоже сохранён."""
        source_url = self._pravo.document_url(item.eo_number)
        raw_api = item.raw_dict()
        doc = self._repo.create_document(item, source_url=source_url, raw_api=raw_api)

        try:
            pdf_data = self._pravo.download_pdf(item.eo_number)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.warning("PDF не найден на портале для %s", item.eo_number)
                return False
            raise
        except ValueError as exc:
            if "не похож на PDF" in str(exc):
                logger.warning("PDF недоступен для %s: %s", item.eo_number, exc)
                return False
            raise

        pdf_raw = self._repo.add_raw_file(
            doc,
            raw_type=RawFileType.pdf,
            data=pdf_data,
            bucket=settings.minio_bucket_raw,
            object_name=f"{item.eo_number}.pdf",
            content_type="application/pdf",
        )

        try:
            snapshot_data = self._pravo.download_page_snapshot(item.eo_number)
            self._repo.add_raw_file(
                doc,
                raw_type=RawFileType.page_snapshot,
                data=snapshot_data,
                bucket=settings.minio_bucket_snapshots,
                object_name=f"{item.eo_number}.html",
                content_type="text/html",
            )
        except Exception:
            logger.warning("Не удалось сохранить снимок страницы для %s", item.eo_number)

        self._session.flush()
        self._publish_kafka(TOPIC_DOCUMENT_DISCOVERED, {"eo_number": item.eo_number, "document_id": doc.id})
        self._publish_kafka(
            TOPIC_RAW_STORED,
            {"eo_number": item.eo_number, "document_id": doc.id, "raw_id": pdf_raw.id},
        )
        return True

    def _publish_kafka(self, topic: str, payload: dict) -> None:
        if self._kafka is None:
            return
        self._kafka.produce(topic, json.dumps(payload).encode())
        self._kafka.poll(0)

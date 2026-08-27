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
    date_from: str | None = None
    date_to: str | None = None
    by_type: dict[str, dict[str, int]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "fetched": self.fetched,
            "new": self.new,
            "skipped": self.skipped,
            "no_pdf": self.no_pdf,
            "errors": self.errors,
            "error_details": self.error_details,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "by_type": self.by_type,
        }


def collect_window(
    *,
    anchor: date | None = None,
    lookback_days: int | None = None,
) -> tuple[date, date]:
    """Окно ежедневного сбора: [anchor − lookback, anchor].

    Cron в 08:00 MSK с lookback=1 → вчера+сегодня: догоняет ФЗ,
    опубликованные после вчерашнего утреннего прогона (гранулярность API — день).
    """
    end = anchor or date.today()
    lookback = settings.collect_lookback_days if lookback_days is None else lookback_days
    start = end - timedelta(days=max(0, int(lookback)))
    return start, end


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

        for target in self._pravo.collect_targets():
            self._collect_target(
                target,
                period_type=period_type if target_date is None else "day",
                target_date=target_date,
                stats=stats,
            )

        self._session.commit()
        return stats

    def _collect_catalog(
        self,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> CollectStats:
        """Полный каталог всех целей сбора из API (§3 ТЗ) — публикации president/government,
        не бэкофилл изменяемых актов (§8.3)."""
        stats = CollectStats()
        sync_reference_data(self._session, self._pravo)

        for target in self._pravo.collect_targets():
            logger.info(
                "Полный каталог API: %s — %s (официальный источник, данные с ~2011 года)",
                target.block,
                target.key(),
            )
            seen: set[str] = set()
            for item in self._pravo.iter_all_documents(
                target,
                publish_date_from=date_from,
                publish_date_to=date_to,
            ):
                if item.eo_number in seen:
                    continue
                seen.add(item.eo_number)
                self._ingest_or_skip(item, stats, type_key=target.key())

        self._session.commit()
        return stats

    def _collect_range(self, date_from: date, date_to: date) -> CollectStats:
        if date_from > date_to:
            date_from, date_to = date_to, date_from

        stats = CollectStats(
            date_from=date_from.isoformat(),
            date_to=date_to.isoformat(),
        )
        sync_reference_data(self._session, self._pravo)

        current = date_from
        while current <= date_to:
            logger.info("Сбор за %s", current.isoformat())
            for target in self._pravo.collect_targets():
                self._collect_target(
                    target,
                    period_type="day",
                    target_date=current,
                    stats=stats,
                )
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

    def _collect_target(
        self,
        target,
        *,
        period_type: str,
        target_date: date | None,
        stats: CollectStats,
    ) -> None:
        logger.info("Сбор типа %s", target.key())
        seen: set[str] = set()
        for item in self._pravo.iter_documents(
            target,
            period_type=period_type,
            target_date=target_date,
        ):
            if item.eo_number in seen:
                continue
            seen.add(item.eo_number)
            self._ingest_or_skip(item, stats, type_key=target.key())

    def _ingest_or_skip(
        self,
        item: PravoDocumentItem,
        stats: CollectStats,
        *,
        type_key: str | None = None,
    ) -> None:
        stats.fetched += 1
        if self._repo.exists(item.eo_number):
            stats.skipped += 1
            self._bump_type(stats, type_key, "skipped", 1)
            if stats.skipped % 500 == 0:
                logger.info("Пропущено (уже в базе): %d, новых: %d", stats.skipped, stats.new)
            return
        try:
            has_pdf = self._ingest_item(item)
            stats.new += 1
            self._bump_type(stats, type_key, "new", 1)
            if not has_pdf:
                stats.no_pdf += 1
            self._session.commit()
            if has_pdf:
                logger.info("Сохранён новый документ: %s — %s", item.eo_number, item.name)
            else:
                logger.info(
                    "Сохранён новый документ без PDF (метаданные): %s — %s",
                    item.eo_number,
                    item.name,
                )
        except Exception as exc:
            stats.errors += 1
            self._bump_type(stats, type_key, "errors", 1)
            msg = f"{item.eo_number}: {exc}"
            stats.error_details.append(msg)
            logger.exception("Ошибка при сохранении %s", item.eo_number)
            self._session.rollback()

    @staticmethod
    def _bump_type(stats: CollectStats, type_key: str | None, field: str, amount: int) -> None:
        if not type_key:
            return
        bucket = stats.by_type.setdefault(type_key, {})
        bucket[field] = bucket.get(field, 0) + amount

    def _ingest_item(self, item: PravoDocumentItem) -> bool:
        """Сохраняет документ. Возвращает True, если PDF тоже сохранён."""
        source_url = self._pravo.document_url(item.eo_number)
        raw_api = item.raw_dict()
        doc = self._repo.create_document(
            item, source_url=source_url, raw_api=raw_api, pravo=self._pravo
        )

        try:
            raw_data, kind = self._pravo.download_raw_file(item.eo_number)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.warning("PDF не найден на портале для %s", item.eo_number)
                return False
            raise
        except ValueError as exc:
            logger.warning("Файл недоступен для %s: %s", item.eo_number, exc)
            return False

        if kind == "tiff_zip":
            self._repo.add_raw_file(
                doc,
                raw_type=RawFileType.zip,
                data=raw_data,
                bucket=settings.minio_bucket_raw,
                object_name=f"{item.eo_number}.tiff.zip",
                content_type="application/zip",
            )
            from explainlaw.extraction.tiff_zip import tiff_zip_to_pdf

            pdf_data = tiff_zip_to_pdf(raw_data)
        else:
            pdf_data = raw_data

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

        self._store_optional_raw(doc, item)
        self._session.flush()
        self._publish_kafka(TOPIC_DOCUMENT_DISCOVERED, {"eo_number": item.eo_number, "document_id": doc.id})
        self._publish_kafka(
            TOPIC_RAW_STORED,
            {"eo_number": item.eo_number, "document_id": doc.id, "raw_id": pdf_raw.id},
        )
        return True

    def _store_optional_raw(self, doc, item: PravoDocumentItem) -> None:
        if item.zip_file_length and item.zip_file_length > 0:
            try:
                zip_data = self._pravo.download_zip(item.eo_number)
                self._repo.add_raw_file(
                    doc,
                    raw_type=RawFileType.zip,
                    data=zip_data,
                    bucket=settings.minio_bucket_raw,
                    object_name=f"{item.eo_number}.zip",
                    content_type="application/zip",
                )
            except Exception:
                logger.warning("ZIP недоступен для %s", item.eo_number)
        if item.has_svg:
            try:
                svg_data = self._pravo.download_svg(item.eo_number)
                self._repo.add_raw_file(
                    doc,
                    raw_type=RawFileType.svg,
                    data=svg_data,
                    bucket=settings.minio_bucket_raw,
                    object_name=f"{item.eo_number}.svg",
                    content_type="image/svg+xml",
                )
            except Exception:
                logger.warning("SVG недоступен для %s", item.eo_number)

    def backfill_missing_pdfs(self, *, limit: int | None = None) -> dict:
        """Догон PDF/TIFF-ZIP для документов без сырья (§4.1)."""
        from sqlalchemy import exists, select

        from explainlaw.db.models import NpaDocument, NpaRaw
        from explainlaw.extraction.tiff_zip import tiff_zip_to_pdf

        has_pdf = exists().where(
            NpaRaw.document_id == NpaDocument.id,
            NpaRaw.raw_type == RawFileType.pdf,
        )
        stmt = (
            select(NpaDocument)
            .where(~has_pdf)
            .order_by(NpaDocument.publish_date_short.desc())
        )
        if limit:
            stmt = stmt.limit(limit)
        docs = list(self._session.execute(stmt).scalars().all())
        stats = {"candidates": len(docs), "fetched": 0, "not_found": 0, "errors": 0}
        for doc in docs:
            try:
                raw_data, kind = self._pravo.download_raw_file(doc.eo_number)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    stats["not_found"] += 1
                    continue
                stats["errors"] += 1
                continue
            except ValueError:
                stats["not_found"] += 1
                continue
            except Exception:
                stats["errors"] += 1
                logger.exception("PDF backfill failed %s", doc.eo_number)
                continue

            if kind == "tiff_zip":
                self._repo.add_raw_file(
                    doc,
                    raw_type=RawFileType.zip,
                    data=raw_data,
                    bucket=settings.minio_bucket_raw,
                    object_name=f"{doc.eo_number}.tiff.zip",
                    content_type="application/zip",
                )
                try:
                    pdf_data = tiff_zip_to_pdf(raw_data)
                except Exception:
                    stats["errors"] += 1
                    continue
            else:
                pdf_data = raw_data

            self._repo.add_raw_file(
                doc,
                raw_type=RawFileType.pdf,
                data=pdf_data,
                bucket=settings.minio_bucket_raw,
                object_name=f"{doc.eo_number}.pdf",
                content_type="application/pdf",
            )
            stats["fetched"] += 1
            self._session.commit()
        return stats

    def _publish_kafka(self, topic: str, payload: dict) -> None:
        if self._kafka is None:
            return
        try:
            self._kafka.produce(topic, json.dumps(payload).encode())
            self._kafka.poll(0)
        except Exception:
            logger.warning("Не удалось опубликовать событие %s", topic, exc_info=True)

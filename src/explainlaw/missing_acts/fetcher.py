"""Загрузка недостающих актов из официального API (§8.3, этап 2)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from explainlaw.collector.refs import sync_reference_data
from explainlaw.collector.service import DailyCollector
from explainlaw.db.models import MissingActStatus, MissingActsQueue
from explainlaw.extraction.act_identifier import find_document_by_identifier
from explainlaw.pravo.client import PravoApiClient
from explainlaw.pravo.models import PravoDocumentItem
from explainlaw.storage.object_store import ObjectStorage

logger = logging.getLogger(__name__)


@dataclass
class FetchMissingStats:
    queued: int = 0
    fetched: int = 0
    not_found: int = 0
    skipped: int = 0
    errors: int = 0
    error_details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "queued": self.queued,
            "fetched": self.fetched,
            "not_found": self.not_found,
            "skipped": self.skipped,
            "errors": self.errors,
            "error_details": self.error_details,
        }


def _normalize_name(raw: str | None) -> str:
    if not raw:
        return ""
    return re.sub(r"\s+", " ", raw.strip().lower())


def _normalize_number(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = raw.strip().upper().replace(" ", "")
    if not cleaned.endswith("-ФЗ") and cleaned.isdigit():
        return f"{cleaned}-ФЗ"
    return cleaned


def _item_matches(identifier: dict, item: PravoDocumentItem) -> bool:
    expected_number = _normalize_number(identifier.get("number"))
    item_number = _normalize_number(item.number)
    if expected_number and item_number and expected_number != item_number:
        return False

    expected_date = identifier.get("date")
    if expected_date and item.document_date:
        item_date = item.document_date.date() if hasattr(item.document_date, "date") else None
        if item_date and item_date.isoformat() != expected_date:
            return False

    expected_name = _normalize_name(identifier.get("name"))
    if expected_name and item.name:
        if expected_name[:30] not in _normalize_name(item.name):
            return False

    return bool(expected_number or expected_name)


def find_act_in_catalog(
    client: PravoApiClient,
    identifier: dict,
    *,
    fz_type_id,
) -> PravoDocumentItem | None:
    """Ищет акт в каталоге API по номеру и дате."""
    date_from = None
    date_to = None
    if identifier.get("date"):
        act_date = date.fromisoformat(identifier["date"])
        date_from = act_date - timedelta(days=30)
        date_to = act_date + timedelta(days=365)

    for item in client.iter_all_federal_laws(
        fz_type_id=fz_type_id,
        publish_date_from=date_from,
        publish_date_to=date_to,
    ):
        if _item_matches(identifier, item):
            return item

    if date_from:
        for item in client.iter_all_federal_laws(fz_type_id=fz_type_id):
            if _item_matches(identifier, item):
                return item

    return None


class MissingActsFetcher:
    def __init__(
        self,
        session: Session,
        storage: ObjectStorage,
        *,
        pravo: PravoApiClient | None = None,
    ) -> None:
        self._session = session
        self._storage = storage
        self._pravo = pravo or PravoApiClient()
        self._owns_pravo = pravo is None
        self._collector = DailyCollector(session, storage, pravo=self._pravo)

    def close(self) -> None:
        self._collector.close()

    def fetch(self, *, limit: int = 10) -> FetchMissingStats:
        stats = FetchMissingStats()
        sync_reference_data(self._session, self._pravo)
        fz_type_id = self._pravo.resolve_fz_type_id()

        pending = self._session.execute(
            select(MissingActsQueue)
            .where(MissingActsQueue.status == MissingActStatus.pending)
            .order_by(MissingActsQueue.request_count.desc(), MissingActsQueue.created_at)
            .limit(limit)
        ).scalars().all()
        stats.queued = len(pending)

        for row in pending:
            identifier = row.referenced_act_identifier
            if find_document_by_identifier(self._session, identifier):
                row.status = MissingActStatus.fetched
                stats.skipped += 1
                continue

            try:
                item = find_act_in_catalog(self._pravo, identifier, fz_type_id=fz_type_id)
            except Exception as exc:
                stats.errors += 1
                stats.error_details.append(f"{identifier}: {exc}")
                row.status = MissingActStatus.failed
                continue

            if item is None:
                stats.not_found += 1
                continue

            try:
                if self._collector._repo.exists(item.eo_number):
                    row.status = MissingActStatus.fetched
                    stats.skipped += 1
                elif self._collector.ingest_one(item):
                    row.status = MissingActStatus.fetched
                    stats.fetched += 1
                    logger.info("Загружен недостающий акт: %s", item.eo_number)
                else:
                    row.status = MissingActStatus.fetched
                    stats.skipped += 1
            except Exception as exc:
                stats.errors += 1
                stats.error_details.append(f"{item.eo_number}: {exc}")
                row.status = MissingActStatus.failed
                self._session.rollback()
                continue

        self._session.commit()
        return stats

"""Ежедневный конвейер: сбор → обработка → гейты → очередь актов (§7.1, §11)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from explainlaw.collector.service import DailyCollector, collect_window
from explainlaw.content.publisher import WeeklyPublisher
from explainlaw.db.models import PipelineJobType
from explainlaw.gates.runner import GateRunner
from explainlaw.missing_acts.fetcher import MissingActsFetcher
from explainlaw.observability.health import check_health
from explainlaw.observability.health import send_alerts as dispatch_alerts
from explainlaw.observability.recorder import record_run
from explainlaw.pipeline.processor import DocumentProcessor
from explainlaw.storage.object_store import ObjectStorage

logger = logging.getLogger(__name__)


@dataclass
class DailyRunStats:
    collect: dict = field(default_factory=dict)
    process: dict = field(default_factory=dict)
    gate: dict = field(default_factory=dict)
    fetch_missing: dict = field(default_factory=dict)
    publish: dict | None = None
    health: dict = field(default_factory=dict)
    alert_sent: bool = False

    def to_dict(self) -> dict:
        return {
            "collect": self.collect,
            "process": self.process,
            "gate": self.gate,
            "fetch_missing": self.fetch_missing,
            "publish": self.publish,
            "health": self.health,
            "alert_sent": self.alert_sent,
        }


class DailyPipeline:
    def __init__(
        self,
        session: Session,
        storage: ObjectStorage,
        *,
        kafka_producer=None,
    ) -> None:
        self._session = session
        self._storage = storage
        self._kafka = kafka_producer

    def run(
        self,
        *,
        target_date: date | None = None,
        process_limit: int | None = None,
        fetch_missing_limit: int = 3,
        weekly_publish: bool = False,
        send_alerts: bool = True,
    ) -> DailyRunStats:
        stats = DailyRunStats()
        collector = DailyCollector(self._session, self._storage)
        fetcher = MissingActsFetcher(self._session, self._storage, pravo=collector._pravo)

        try:
            # Не только «сегодня»: ФЗ часто выходят после 08:00 в тот же день.
            # Окно [вчера, сегодня] при cron 08:00 ≈ прошедшие сутки.
            date_from, date_to = collect_window(anchor=target_date or date.today())
            logger.info(
                "Daily collect window %s .. %s",
                date_from.isoformat(),
                date_to.isoformat(),
            )
            collect_stats = collector.collect(date_from=date_from, date_to=date_to)
            stats.collect = collect_stats.to_dict()
            record_run(
                self._session,
                job_type=PipelineJobType.collect,
                metrics=stats.collect,
            )
            # Фиксируем collect сразу: иначе падение process (Kafka и т.п.)
            # откатывает pipeline_run и health орёт «нет успешного сбора».
            self._session.commit()

            processor = DocumentProcessor(
                self._session, self._storage, kafka_producer=self._kafka
            )
            process_stats = processor.process(limit=process_limit)
            stats.process = process_stats.to_dict()
            record_run(
                self._session,
                job_type=PipelineJobType.process,
                metrics=stats.process,
            )
            self._session.commit()

            gate_stats = GateRunner(self._session, kafka_producer=self._kafka).run(
                limit=process_limit
            )
            stats.gate = gate_stats.to_dict()
            record_run(
                self._session,
                job_type=PipelineJobType.gate,
                metrics=stats.gate,
            )
            self._session.commit()

            fetch_stats = fetcher.fetch(limit=fetch_missing_limit)
            stats.fetch_missing = fetch_stats.to_dict()
            record_run(
                self._session,
                job_type=PipelineJobType.fetch_missing,
                metrics=stats.fetch_missing,
            )
            self._session.commit()

            if weekly_publish:
                publish_stats = WeeklyPublisher(
                    self._session, kafka_producer=self._kafka
                ).run(mark_published=True)
                stats.publish = publish_stats.to_dict()
                record_run(
                    self._session,
                    job_type=PipelineJobType.publish,
                    metrics=stats.publish,
                )
                self._session.commit()

            stats.health = check_health(self._session)
            if send_alerts:
                stats.alert_sent = dispatch_alerts(stats.health)

            record_run(
                self._session,
                job_type=PipelineJobType.daily,
                metrics=stats.to_dict(),
            )
            self._session.commit()

        finally:
            fetcher.close()
            collector.close()

        return stats

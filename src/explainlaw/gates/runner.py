"""Оркестратор гейтов качества (§9)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, selectinload

from explainlaw.db.models import (
    GateFlag,
    GateStatus,
    NpaDelta,
    NpaDocument,
    NpaSummary,
    NpaText,
)
from explainlaw.extraction.changes import is_amendment_law
from explainlaw.gates.delta_gate import run_delta_gate
from explainlaw.gates.post_bank import promote_to_post_bank
from explainlaw.gates.summary_gate import run_summary_gate
from explainlaw.pipeline.topics import TOPIC_GATE_RESULT, TOPIC_POST_READY

logger = logging.getLogger(__name__)


@dataclass
class GateRunStats:
    candidates: int = 0
    passed: int = 0
    flagged: int = 0
    skipped: int = 0
    post_bank_added: int = 0
    errors: int = 0
    error_details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "candidates": self.candidates,
            "passed": self.passed,
            "flagged": self.flagged,
            "skipped": self.skipped,
            "post_bank_added": self.post_bank_added,
            "errors": self.errors,
            "error_details": self.error_details,
        }


class GateRunner:
    def __init__(
        self,
        session: Session,
        *,
        kafka_producer=None,
        force: bool = False,
        amendments_only: bool = False,
    ) -> None:
        self._session = session
        self._kafka = kafka_producer
        self._force = force
        self._amendments_only = amendments_only

    def run(self, *, limit: int | None = None) -> GateRunStats:
        stats = GateRunStats()
        docs = self._candidate_documents(limit)
        stats.candidates = len(docs)

        for doc in docs:
            try:
                outcome, created_post = self._run_document(doc)
                if outcome == "skipped":
                    stats.skipped += 1
                elif outcome == "passed":
                    stats.passed += 1
                    if created_post:
                        stats.post_bank_added += 1
                else:
                    stats.flagged += 1
            except Exception as exc:
                stats.errors += 1
                stats.error_details.append(f"{doc.eo_number}: {exc}")
                logger.exception("Ошибка гейтов для %s", doc.eo_number)
                self._session.rollback()

        if stats.passed or stats.flagged:
            self._session.commit()
        return stats

    def run_single(self, doc: NpaDocument) -> tuple[str, bool]:
        """Проверить один документ (для вызова из конвейера process)."""
        outcome, created = self._run_document(doc)
        return outcome, created

    def _candidate_documents(self, limit: int | None) -> list[NpaDocument]:
        stmt = (
            select(NpaDocument)
            .join(NpaSummary, NpaSummary.document_id == NpaDocument.id)
            .options(
                selectinload(NpaDocument.text),
                selectinload(NpaDocument.summaries),
                selectinload(NpaDocument.delta),
            )
            .order_by(NpaDocument.publish_date_short.desc())
        )
        if self._amendments_only:
            stmt = stmt.join(NpaDelta, NpaDelta.document_id == NpaDocument.id)
        elif not self._force:
            stmt = stmt.where(NpaSummary.gate_status == GateStatus.pending)
        if self._amendments_only:
            stmt = stmt.where(
                or_(
                    NpaDocument.name.ilike("%внесении изменен%"),
                    NpaDocument.name.ilike("%внесении изменений%"),
                )
            )
            stmt = stmt.where(~NpaDocument.name.ilike("%О ратификации%"))
            stmt = stmt.where(~NpaDocument.name.ilike("%О принятии Протокола%"))
        if limit:
            stmt = stmt.limit(limit)
        return list(self._session.execute(stmt).scalars().unique().all())

    def _run_document(self, doc: NpaDocument) -> tuple[str, bool]:
        if not doc.text or not doc.summaries:
            return "skipped", False

        summary = doc.summaries[0]
        delta = doc.delta

        if not delta and not is_amendment_law(doc.name):
            return "skipped", False

        if self._force:
            self._session.execute(delete(GateFlag).where(GateFlag.document_id == doc.id))

        delta_result = run_delta_gate(doc, doc.text.full_text, delta)
        for flag in delta_result.flags:
            self._session.add(
                GateFlag(
                    document_id=doc.id,
                    summary_id=summary.id,
                    gate_number=flag.gate_number,
                    flag_type=flag.flag_type,
                    flag_details=flag.flag_details,
                )
            )

        all_flags = list(delta_result.flags)
        if delta_result.passed:
            summary_result = run_summary_gate(doc, summary, delta)
            for flag in summary_result.flags:
                self._session.add(
                    GateFlag(
                        document_id=doc.id,
                        summary_id=summary.id,
                        gate_number=flag.gate_number,
                        flag_type=flag.flag_type,
                        flag_details=flag.flag_details,
                    )
                )
            all_flags.extend(summary_result.flags)

        passed = len(all_flags) == 0
        summary.gate_status = GateStatus.passed if passed else GateStatus.flagged

        payload = {
            "document_id": doc.id,
            "eo_number": doc.eo_number,
            "passed": passed,
            "flag_count": len(all_flags),
        }
        self._publish(TOPIC_GATE_RESULT, payload)

        if passed and delta:
            _, created = promote_to_post_bank(self._session, doc=doc, summary=summary, delta=delta)
            self._publish(TOPIC_POST_READY, payload)
            logger.info("Гейты пройдены: %s", doc.eo_number)
            return "passed", created

        logger.info("Гейты: флаги для %s (%d)", doc.eo_number, len(all_flags))
        return "flagged", False

    def _publish(self, topic: str, payload: dict) -> None:
        if self._kafka is None:
            return
        self._kafka.produce(topic, json.dumps(payload).encode())
        self._kafka.poll(0)

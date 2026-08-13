import json
import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import delete, exists, or_, select
from sqlalchemy.orm import Session, selectinload

from explainlaw.db.models import (
    GateStatus,
    NpaDelta,
    NpaDocument,
    NpaEnactment,
    NpaRaw,
    NpaRelation,
    NpaSummary,
    NpaText,
    NormChangeEvent,
    RawFileType,
    TextExtractionMethod,
)
from explainlaw.content.act_groups import assign_act_group
from explainlaw.content.sectors import assign_sectors
from explainlaw.delta.builder import build_delta_for_document
from explainlaw.extraction.act_identifier import find_document_by_identifier
from explainlaw.extraction.changes import (
    effective_date_for_article,
    extract_scoped_norm_changes,
    is_amendment_law,
)
from explainlaw.extraction.enactment import extract_enactments
from explainlaw.extraction.fragment import extract_summary_fragment
from explainlaw.extraction.pdf_extractor import extract_text_from_pdf
from explainlaw.extraction.quality import is_text_unreadable
from explainlaw.extraction.relations import RelationMatch, extract_relations
from explainlaw.extraction.retry_ocr import retry_extract_with_llm_cleanup
from explainlaw.gates.runner import GateRunner
from explainlaw.llm.gateway import generate_summary
from explainlaw.missing_acts.queue import enqueue_from_relations
from explainlaw.norms.event_writer import persist_norm_changes
from explainlaw.pipeline.topics import (
    TOPIC_DELTA_COMPUTED,
    TOPIC_SUMMARY_GENERATED,
    TOPIC_TEXT_EXTRACTED,
)
from explainlaw.pravo.client import PravoApiClient
from explainlaw.storage.object_store import ObjectStorage

logger = logging.getLogger(__name__)


@dataclass
class ProcessStats:
    candidates: int = 0
    text_extracted: int = 0
    summarized: int = 0
    relations_linked: int = 0
    missing_acts_enqueued: int = 0
    deltas_built: int = 0
    sectors_assigned: int = 0
    act_groups_assigned: int = 0
    gates_passed: int = 0
    gates_flagged: int = 0
    excluded_unreadable: int = 0
    skipped: int = 0
    errors: int = 0
    error_details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "candidates": self.candidates,
            "text_extracted": self.text_extracted,
            "summarized": self.summarized,
            "relations_linked": self.relations_linked,
            "missing_acts_enqueued": self.missing_acts_enqueued,
            "deltas_built": self.deltas_built,
            "sectors_assigned": self.sectors_assigned,
            "act_groups_assigned": self.act_groups_assigned,
            "gates_passed": self.gates_passed,
            "gates_flagged": self.gates_flagged,
            "excluded_unreadable": self.excluded_unreadable,
            "skipped": self.skipped,
            "errors": self.errors,
            "error_details": self.error_details,
        }


class DocumentProcessor:
    """Конвейер 1b+: PDF → текст → связи → norm events → дельта → сводка."""

    def __init__(
        self,
        session: Session,
        storage: ObjectStorage,
        *,
        kafka_producer=None,
        force: bool = False,
        amendments_only: bool = False,
        rebuild_deltas_only: bool = False,
        resume: bool = False,
        min_text_chars: int = 200,
        publish_date: date | None = None,
        pravo: PravoApiClient | None = None,
    ) -> None:
        self._session = session
        self._storage = storage
        self._kafka = kafka_producer
        self._force = force
        self._amendments_only = amendments_only
        self._rebuild_deltas_only = rebuild_deltas_only
        self._resume = resume
        self._min_text_chars = min_text_chars
        self._publish_date = publish_date
        self._pravo = pravo or PravoApiClient()

    def process(self, *, limit: int | None = None) -> ProcessStats:
        stats = ProcessStats()
        docs = self._pending_documents(limit)
        stats.candidates = len(docs)

        for doc in docs:
            try:
                if doc.text and doc.summaries and doc.delta and not self._force:
                    gate_pending = doc.summaries[0].gate_status == GateStatus.pending
                    if not gate_pending:
                        stats.skipped += 1
                        continue
                result = self._process_document(doc)
                if result.get("excluded_unreadable"):
                    stats.excluded_unreadable += 1
                    logger.warning("Исключён (нечитаемый OCR даже после retry) %s", doc.eo_number)
                    continue
                if result.get("text_extracted"):
                    stats.text_extracted += 1
                if result.get("summarized"):
                    stats.summarized += 1
                stats.relations_linked += result.get("relations_linked", 0)
                stats.missing_acts_enqueued += result.get("missing_acts_enqueued", 0)
                if result.get("delta_built"):
                    stats.deltas_built += 1
                stats.sectors_assigned += result.get("sectors_assigned", 0)
                stats.act_groups_assigned += result.get("act_groups_assigned", 0)
                if result.get("gate_passed"):
                    stats.gates_passed += 1
                if result.get("gate_flagged"):
                    stats.gates_flagged += 1
                if result.get("text_extracted"):
                    logger.info("Извлечён текст %s", doc.eo_number)
                elif result.get("summarized"):
                    logger.info("Сводка %s", doc.eo_number)
                else:
                    logger.info("Обработан %s (дозаполнение связей/дельты)", doc.eo_number)
                if any(
                    result.get(key)
                    for key in (
                        "text_extracted",
                        "summarized",
                        "delta_built",
                        "gate_passed",
                        "gate_flagged",
                        "relations_linked",
                        "missing_acts_enqueued",
                        "sectors_assigned",
                        "act_groups_assigned",
                    )
                ):
                    self._session.commit()
            except Exception as exc:
                stats.errors += 1
                stats.error_details.append(f"{doc.eo_number}: {exc}")
                logger.exception("Ошибка обработки %s", doc.eo_number)
                self._session.rollback()
                continue

        return stats

    def _pending_documents(self, limit: int | None) -> list[NpaDocument]:
        load_options = (
            selectinload(NpaDocument.raw_files),
            selectinload(NpaDocument.text),
            selectinload(NpaDocument.summaries),
            selectinload(NpaDocument.enactments),
            selectinload(NpaDocument.relations_out),
            selectinload(NpaDocument.delta),
        )
        if self._force or self._amendments_only:
            stmt = (
                select(NpaDocument)
                .options(*load_options)
                .join(NpaText, NpaText.document_id == NpaDocument.id)
                .order_by(NpaDocument.publish_date_short.asc(), NpaDocument.id.asc())
            )
            if self._amendments_only:
                stmt = stmt.where(
                    or_(
                        NpaDocument.name.ilike("%внесении изменен%"),
                        NpaDocument.name.ilike("%внесении изменений%"),
                    )
                )
                stmt = stmt.where(~NpaDocument.name.ilike("%О ратификации%"))
                stmt = stmt.where(~NpaDocument.name.ilike("%О принятии Протокола%"))
            if self._resume:
                # --resume: только поправки без дельты
                stmt = stmt.outerjoin(NpaDelta, NpaDelta.document_id == NpaDocument.id).where(
                    NpaDelta.id.is_(None)
                )
            if self._publish_date is not None:
                stmt = stmt.where(NpaDocument.publish_date_short == self._publish_date)
            if limit:
                stmt = stmt.limit(limit)
            return list(self._session.execute(stmt).scalars().unique().all())

        has_summary = exists().where(NpaSummary.document_id == NpaDocument.id)
        has_pending_gate = exists().where(
            NpaSummary.document_id == NpaDocument.id,
            NpaSummary.gate_status == GateStatus.pending,
        )
        stmt = (
            select(NpaDocument)
            .options(*load_options)
            .outerjoin(NpaText, NpaText.document_id == NpaDocument.id)
            .outerjoin(NpaDelta, NpaDelta.document_id == NpaDocument.id)
            .where(
                or_(
                    NpaText.id.is_(None),
                    ~has_summary,
                    NpaDelta.id.is_(None),
                    has_pending_gate,
                )
            )
            .where(NpaText.is_unreadable.isnot(True))
            .order_by(
                NpaText.id.is_(None).desc(),
                NpaDocument.publish_date_short.desc(),
            )
        )
        if self._publish_date is not None:
            stmt = stmt.where(NpaDocument.publish_date_short == self._publish_date)
        if limit:
            stmt = stmt.limit(limit)
        return list(self._session.execute(stmt).scalars().all())

    def _process_document(self, doc: NpaDocument) -> dict:
        pdf_raw = self._find_pdf(doc)
        if pdf_raw is None:
            raise ValueError("PDF не найден в сырье")

        text_extracted = False
        if doc.text is None or (self._force and not self._rebuild_deltas_only):
            pdf_bytes = self._storage.get_by_path(pdf_raw.storage_path)
            extraction = extract_text_from_pdf(pdf_bytes)

            if is_text_unreadable(extraction.text, extraction.page_count):
                logger.warning("Текст %s нечитаем, пробую передокачку + переOCR", doc.eo_number)
                fresh_pdf_bytes = self._pravo.download_pdf(doc.eo_number)
                retry_text, still_unreadable = retry_extract_with_llm_cleanup(fresh_pdf_bytes)
                if still_unreadable:
                    if doc.text:
                        self._session.delete(doc.text)
                        self._session.flush()
                    self._session.add(
                        NpaText(
                            document_id=doc.id,
                            full_text=retry_text,
                            extraction_method=extraction.method,
                            page_count_extracted=extraction.page_count,
                            is_unreadable=True,
                        )
                    )
                    self._session.commit()
                    return {"excluded_unreadable": True}
                extraction.text = retry_text
                extraction.method = TextExtractionMethod.ocr

            if doc.text:
                self._session.delete(doc.text)
                self._session.flush()
            text_row = NpaText(
                document_id=doc.id,
                full_text=extraction.text,
                extraction_method=extraction.method,
                page_count_extracted=extraction.page_count,
            )
            self._session.add(text_row)
            self._session.flush()
            text_extracted = True
            self._publish(TOPIC_TEXT_EXTRACTED, {"document_id": doc.id, "eo_number": doc.eo_number})
        else:
            text_row = doc.text

        full_text = text_row.full_text
        if self._rebuild_deltas_only and len((full_text or "").strip()) < self._min_text_chars:
            raise ValueError(
                f"текст слишком короткий для дельты ({len((full_text or '').strip())} < {self._min_text_chars})"
            )
        fragment = extract_summary_fragment(full_text)

        if not doc.enactments or (self._force and not self._rebuild_deltas_only):
            if self._force and doc.enactments:
                self._session.execute(
                    delete(NpaEnactment).where(NpaEnactment.document_id == doc.id)
                )
            for item in extract_enactments(full_text):
                self._session.add(
                    NpaEnactment(
                        document_id=doc.id,
                        effective_date=item.effective_date,
                        unit_address=item.unit_address,
                        conditions=item.conditions,
                        text_fragment=item.text_fragment,
                    )
                )
            self._session.flush()

        enactments = list(
            self._session.execute(
                select(NpaEnactment).where(NpaEnactment.document_id == doc.id)
            ).scalars()
        )

        relation_matches: list = []
        if not doc.relations_out or (self._force and not self._rebuild_deltas_only):
            if self._force and doc.relations_out:
                self._session.execute(
                    delete(NpaRelation).where(NpaRelation.source_document_id == doc.id)
                )
            relation_matches = extract_relations(doc.name, full_text)
            for item in relation_matches:
                target_doc = find_document_by_identifier(self._session, item.target_act_identifier)
                self._session.add(
                    NpaRelation(
                        source_document_id=doc.id,
                        target_act_identifier=item.target_act_identifier,
                        target_document_id=target_doc.id if target_doc else None,
                        relation_type=item.relation_type,
                        target_name_text=item.target_name_text,
                    )
                )
        else:
            relation_matches = [
                RelationMatch(
                    target_act_identifier=r.target_act_identifier,
                    target_name_text=r.target_name_text or "",
                    relation_type=r.relation_type,
                )
                for r in doc.relations_out
            ]

        relations_linked = sum(
            1
            for r in relation_matches
            if find_document_by_identifier(self._session, r.target_act_identifier)
        )

        missing_enqueued = enqueue_from_relations(
            self._session, document_id=doc.id, relations=relation_matches
        )

        scoped = extract_scoped_norm_changes(full_text, doc_name=doc.name)

        delta_built = False
        if scoped:
            if self._force and (doc.delta or self._session.execute(
                select(NormChangeEvent).where(NormChangeEvent.source_document_id == doc.id).limit(1)
            ).scalar_one_or_none()):
                with self._session.begin_nested():
                    self._session.execute(
                        delete(NormChangeEvent).where(
                            NormChangeEvent.source_document_id == doc.id
                        )
                    )
                    if doc.delta:
                        self._session.delete(doc.delta)
                        self._session.flush()
                    order = 0
                    for item in scoped:
                        target_doc = find_document_by_identifier(
                            self._session, item.target_act_identifier
                        )
                        target_text = None
                        if target_doc:
                            target_text_row = self._session.execute(
                                select(NpaText).where(NpaText.document_id == target_doc.id)
                            ).scalar_one_or_none()
                            target_text = target_text_row.full_text if target_text_row else None

                        eff = effective_date_for_article(
                            enactments,
                            item.source_article,
                            enactments[0].effective_date if enactments else None,
                        )
                        draft = item.draft
                        draft.effective_date = eff

                        persist_norm_changes(
                            self._session,
                            source_document_id=doc.id,
                            parent_act_identifier=item.target_act_identifier,
                            enactment_date=eff,
                            drafts=[draft],
                            raw_reference_id=pdf_raw.id,
                            target_full_text=target_text,
                            apply_order_start=order,
                        )
                        order += 1

                    new_delta = build_delta_for_document(self._session, doc, full_text)
                    if not new_delta:
                        raise ValueError("дельта не собрана после извлечения")
                delta_built = True
            else:
                order = 0
                for item in scoped:
                    target_doc = find_document_by_identifier(
                        self._session, item.target_act_identifier
                    )
                    target_text = None
                    if target_doc:
                        target_text_row = self._session.execute(
                            select(NpaText).where(NpaText.document_id == target_doc.id)
                        ).scalar_one_or_none()
                        target_text = target_text_row.full_text if target_text_row else None

                    eff = effective_date_for_article(
                        enactments,
                        item.source_article,
                        enactments[0].effective_date if enactments else None,
                    )
                    draft = item.draft
                    draft.effective_date = eff

                    persist_norm_changes(
                        self._session,
                        source_document_id=doc.id,
                        parent_act_identifier=item.target_act_identifier,
                        enactment_date=eff,
                        drafts=[draft],
                        raw_reference_id=pdf_raw.id,
                        target_full_text=target_text,
                        apply_order_start=order,
                    )
                    order += 1

                new_delta = build_delta_for_document(self._session, doc, full_text)
                if new_delta:
                    delta_built = True

            if delta_built:
                self._session.refresh(doc, ["delta"])
                delta = doc.delta
                if delta:
                    self._publish(
                        TOPIC_DELTA_COMPUTED,
                        {
                            "document_id": doc.id,
                            "eo_number": doc.eo_number,
                            "completeness": delta.completeness_status.value,
                            "change_count": delta.delta_data.get("change_count", 0),
                        },
                    )
        elif not doc.delta:
            delta = build_delta_for_document(self._session, doc, full_text)
            if delta:
                delta_built = True
                self._publish(
                    TOPIC_DELTA_COMPUTED,
                    {
                        "document_id": doc.id,
                        "eo_number": doc.eo_number,
                        "completeness": delta.completeness_status.value,
                        "change_count": delta.delta_data.get("change_count", 0),
                    },
                )

        sectors_assigned = assign_sectors(self._session, doc, text=full_text)
        act_groups_assigned = 1 if assign_act_group(self._session, doc) else 0

        summarized = False
        if self._force and not self._rebuild_deltas_only:
            for summary in doc.summaries:
                self._session.delete(summary)

        if (not doc.summaries or self._force) and not self._rebuild_deltas_only:
            summary_result = generate_summary(
                number=doc.number,
                document_date=doc.document_date.isoformat() if doc.document_date else None,
                name=doc.name,
                fragment=fragment,
            )
            summary = NpaSummary(
                document_id=doc.id,
                summary_text=summary_result.text,
                title=summary_result.title,
                model_route=summary_result.model_route,
                gate_status=GateStatus.pending,
            )
            self._session.add(summary)
            summarized = True
            self._publish(
                TOPIC_SUMMARY_GENERATED,
                {"document_id": doc.id, "eo_number": doc.eo_number},
            )

        gate_passed = False
        gate_flagged = False
        self._session.flush()
        self._session.refresh(doc, ["delta", "summaries"])
        if doc.delta and doc.summaries:
            gate_runner = GateRunner(
                self._session, kafka_producer=self._kafka, force=self._force
            )
            outcome, _ = gate_runner.run_single(doc)
            gate_passed = outcome == "passed"
            gate_flagged = outcome == "flagged"

        return {
            "text_extracted": text_extracted,
            "summarized": summarized,
            "relations_linked": relations_linked,
            "missing_acts_enqueued": missing_enqueued,
            "delta_built": delta_built,
            "sectors_assigned": sectors_assigned,
            "act_groups_assigned": act_groups_assigned,
            "gate_passed": gate_passed,
            "gate_flagged": gate_flagged,
        }

    def _find_pdf(self, doc: NpaDocument) -> NpaRaw | None:
        for raw in doc.raw_files:
            if raw.raw_type == RawFileType.pdf:
                return raw
        return None

    def _publish(self, topic: str, payload: dict) -> None:
        if self._kafka is None:
            return
        self._kafka.produce(topic, json.dumps(payload).encode())
        self._kafka.poll(0)

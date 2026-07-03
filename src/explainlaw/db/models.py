import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RawFileType(str, enum.Enum):
    pdf = "pdf"
    zip = "zip"
    svg = "svg"
    page_snapshot = "page_snapshot"


class RelationType(str, enum.Enum):
    amends = "amends"
    repeals = "repeals"
    supplements = "supplements"
    references = "references"


class DeltaCompleteness(str, enum.Enum):
    full = "full"
    partial = "partial"


class ModelRoute(str, enum.Enum):
    qwen = "qwen"
    gateway = "gateway"


class GateStatus(str, enum.Enum):
    pending = "pending"
    passed = "passed"
    flagged = "flagged"
    rejected = "rejected"


class MissingActStatus(str, enum.Enum):
    pending = "pending"
    fetched = "fetched"
    failed = "failed"


class PostType(str, enum.Enum):
    digest = "digest"
    single = "single"
    enactment_week = "enactment_week"
    mini_digest = "mini_digest"
    analysis = "analysis"


class PostStatus(str, enum.Enum):
    draft = "draft"
    ready = "ready"
    published = "published"
    rejected = "rejected"


class NormEventType(str, enum.Enum):
    baseline = "baseline"
    amendment = "amendment"


class OperationType(str, enum.Enum):
    replace = "replace"
    supplement = "supplement"
    delete = "delete"
    full_redaction = "full_redaction"


class ApplyKind(str, enum.Enum):
    full_redaction = "full_redaction"
    address_patch = "address_patch"


class ApplyStatus(str, enum.Enum):
    applied = "applied"
    needs_manual = "needs_manual"
    failed = "failed"


class TextExtractionMethod(str, enum.Enum):
    pdf_text = "pdf_text"
    ocr = "ocr"


class PipelineJobType(str, enum.Enum):
    collect = "collect"
    process = "process"
    gate = "gate"
    publish = "publish"
    fetch_missing = "fetch_missing"
    daily = "daily"


class PipelineRunStatus(str, enum.Enum):
    success = "success"
    partial = "partial"
    failed = "failed"


# ---------------------------------------------------------------------------
# Справочники из API (раздел 5.7)
# ---------------------------------------------------------------------------


class RefPublicBlock(Base):
    __tablename__ = "ref_public_block"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)


class RefDocumentType(Base):
    __tablename__ = "ref_document_type"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)


class RefSignatoryAuthority(Base):
    __tablename__ = "ref_signatory_authority"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


# ---------------------------------------------------------------------------
# Документ и сырьё (раздел 5.3)
# ---------------------------------------------------------------------------


class NpaDocument(Base):
    """Ядро записи о ФЗ — реквизиты (Категория 2) + указатели на происхождение."""

    __tablename__ = "npa_document"
    __table_args__ = (
        Index("ix_npa_document_discovered_at", "discovered_at"),
        Index("ix_npa_document_publish_date", "publish_date_short"),
        Index("ix_npa_document_act_group", "act_group_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Natural key из API
    eo_number: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    # Реквизиты (раздел 4.2)
    number: Mapped[str | None] = mapped_column(String(64))
    document_date: Mapped[date | None] = mapped_column(Date)
    name: Mapped[str | None] = mapped_column(Text)
    complex_name: Mapped[str | None] = mapped_column(Text)
    publish_date_short: Mapped[date | None] = mapped_column(Date)
    view_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ref_document_type.id")
    )
    signatory_authority_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ref_signatory_authority.id")
    )

    pages_count: Mapped[int | None] = mapped_column(Integer)
    pdf_file_length: Mapped[int | None] = mapped_column(BigInteger)
    has_svg: Mapped[bool | None] = mapped_column(Boolean)
    zip_file_length: Mapped[int | None] = mapped_column(BigInteger)

    # Категория 1 — происхождение (раздел 4.1)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    api_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # Категория 3 — производное / разметка (раздел 4.3)
    significance_score: Mapped[float | None] = mapped_column(Float)
    included_in_post: Mapped[bool | None] = mapped_column(Boolean)
    act_group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    raw_files: Mapped[list["NpaRaw"]] = relationship(back_populates="document")
    text: Mapped["NpaText | None"] = relationship(back_populates="document", uselist=False)
    enactments: Mapped[list["NpaEnactment"]] = relationship(back_populates="document")
    relations_out: Mapped[list["NpaRelation"]] = relationship(
        back_populates="source_document",
        foreign_keys="NpaRelation.source_document_id",
    )
    delta: Mapped["NpaDelta | None"] = relationship(back_populates="document", uselist=False)
    summaries: Mapped[list["NpaSummary"]] = relationship(back_populates="document")
    sectors: Mapped[list["NpaSector"]] = relationship(back_populates="document")


class NpaRaw(Base):
    """Сырьё Категории 1 — бинарные файлы в объектном хранилище, в БД только указатели."""

    __tablename__ = "npa_raw"
    __table_args__ = (Index("ix_npa_raw_document_id", "document_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("npa_document.id", ondelete="CASCADE"), nullable=False
    )

    raw_type: Mapped[RawFileType] = mapped_column(
        Enum(RawFileType, name="raw_file_type"), nullable=False
    )
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped["NpaDocument"] = relationship(back_populates="raw_files")


class NpaText(Base):
    """Извлечённый полный текст из PDF."""

    __tablename__ = "npa_text"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("npa_document.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    full_text: Mapped[str] = mapped_column(Text, nullable=False)
    extraction_method: Mapped[TextExtractionMethod] = mapped_column(
        Enum(TextExtractionMethod, name="text_extraction_method"), nullable=False
    )
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    page_count_extracted: Mapped[int | None] = mapped_column(Integer)

    document: Mapped["NpaDocument"] = relationship(back_populates="text")


# ---------------------------------------------------------------------------
# Извлечённые сущности (раздел 5.4)
# ---------------------------------------------------------------------------


class NpaEnactment(Base):
    """Вступление в силу ПО ЧАСТЯМ — одна запись на каждую дату/условие."""

    __tablename__ = "npa_enactment"
    __table_args__ = (Index("ix_npa_enactment_document_id", "document_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("npa_document.id", ondelete="CASCADE"), nullable=False
    )

    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    unit_address: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    conditions: Mapped[str | None] = mapped_column(Text)
    text_fragment: Mapped[str | None] = mapped_column(Text)

    document: Mapped["NpaDocument"] = relationship(back_populates="enactments")


class NpaRelation(Base):
    """Типизированные связи между актами (adjacency)."""

    __tablename__ = "npa_relation"
    __table_args__ = (
        Index("ix_npa_relation_source", "source_document_id"),
        Index("ix_npa_relation_target_doc", "target_document_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("npa_document.id", ondelete="CASCADE"), nullable=False
    )

    # Распознанный идентификатор изменяемого акта (номер + дата) — не строка-название
    target_act_identifier: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    target_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("npa_document.id", ondelete="SET NULL")
    )
    relation_type: Mapped[RelationType] = mapped_column(
        Enum(RelationType, name="relation_type"), nullable=False
    )
    target_name_text: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    source_document: Mapped["NpaDocument"] = relationship(
        back_populates="relations_out",
        foreign_keys=[source_document_id],
    )


class NpaDelta(Base):
    """Что именно меняется — дельта с статусом полноты."""

    __tablename__ = "npa_delta"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("npa_document.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    completeness_status: Mapped[DeltaCompleteness] = mapped_column(
        Enum(DeltaCompleteness, name="delta_completeness"), nullable=False
    )
    delta_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    impact_description: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    document: Mapped["NpaDocument"] = relationship(back_populates="delta")


# ---------------------------------------------------------------------------
# ИИ-результаты и разметка (раздел 5.5)
# ---------------------------------------------------------------------------


class SectorDict(Base):
    __tablename__ = "sector_dict"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    parent_code: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("sector_dict.code"), nullable=True
    )


class NpaSector(Base):
    __tablename__ = "npa_sector"

    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("npa_document.id", ondelete="CASCADE"), primary_key=True
    )
    sector_code: Mapped[str] = mapped_column(
        String(64), ForeignKey("sector_dict.code"), primary_key=True
    )
    confidence: Mapped[float | None] = mapped_column(Float)

    document: Mapped["NpaDocument"] = relationship(back_populates="sectors")


class NpaSummary(Base):
    """ИИ-сводка для поста."""

    __tablename__ = "npa_summary"
    __table_args__ = (Index("ix_npa_summary_document_id", "document_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("npa_document.id", ondelete="CASCADE"), nullable=False
    )

    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    model_route: Mapped[ModelRoute] = mapped_column(
        Enum(ModelRoute, name="model_route"), nullable=False
    )
    gate_status: Mapped[GateStatus] = mapped_column(
        Enum(GateStatus, name="gate_status"),
        nullable=False,
        default=GateStatus.pending,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped["NpaDocument"] = relationship(back_populates="summaries")


# ---------------------------------------------------------------------------
# Очереди и контент (раздел 5.6)
# ---------------------------------------------------------------------------


class MissingActsQueue(Base):
    """Очередь недостающих актов — самонаполнение базы."""

    __tablename__ = "missing_acts_queue"
    __table_args__ = (
        Index("ix_missing_acts_status", "status"),
        Index("ix_missing_acts_identifier", "referenced_act_identifier", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    referenced_act_identifier: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    referencing_document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("npa_document.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[MissingActStatus] = mapped_column(
        Enum(MissingActStatus, name="missing_act_status"),
        nullable=False,
        default=MissingActStatus.pending,
    )
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PostBank(Base):
    """Банк готовых карточек и публикаций."""

    __tablename__ = "post_bank"
    __table_args__ = (Index("ix_post_bank_status", "status"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    post_type: Mapped[PostType] = mapped_column(
        Enum(PostType, name="post_type"), nullable=False
    )
    status: Mapped[PostStatus] = mapped_column(
        Enum(PostStatus, name="post_status"),
        nullable=False,
        default=PostStatus.draft,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    items: Mapped[list["PostItem"]] = relationship(back_populates="post")


class PostItem(Base):
    """Связь карточек с постом-дайджестом."""

    __tablename__ = "post_item"
    __table_args__ = (
        UniqueConstraint("post_id", "document_id", name="uq_post_item_post_document"),
        Index("ix_post_item_post_id", "post_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("post_bank.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("npa_document.id", ondelete="CASCADE"), nullable=False
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    post: Mapped["PostBank"] = relationship(back_populates="items")


class GateFlag(Base):
    """Обратная связь контроля качества (гейты 1 и 2)."""

    __tablename__ = "gate_flag"
    __table_args__ = (
        Index("ix_gate_flag_document_id", "document_id"),
        Index("ix_gate_flag_resolved", "resolved"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("npa_document.id", ondelete="SET NULL")
    )
    summary_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("npa_summary.id", ondelete="SET NULL")
    )

    gate_number: Mapped[int] = mapped_column(Integer, nullable=False)
    flag_type: Mapped[str] = mapped_column(String(128), nullable=False)
    flag_details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Версионирование норм (раздел 6.5)
# ---------------------------------------------------------------------------


class Norm(Base):
    """Стабильная идентичность нормы — id отдельно от номера."""

    __tablename__ = "norm"
    __table_args__ = (Index("ix_norm_parent_act", "parent_act_identifier", postgresql_using="gin"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    stable_norm_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)

    parent_act_identifier: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    unit_address: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    change_events: Mapped[list["NormChangeEvent"]] = relationship(back_populates="norm")
    revision_caches: Mapped[list["NormRevisionCache"]] = relationship(back_populates="norm")


class NormChangeEvent(Base):
    """Поток событий — ИСТОЧНИК ИСТИНЫ для версионирования норм."""

    __tablename__ = "norm_change_event"
    __table_args__ = (
        Index("ix_norm_change_event_norm_id", "norm_id"),
        Index("ix_norm_change_event_effective_date", "effective_date"),
        Index(
            "ix_norm_change_event_order",
            "norm_id",
            "effective_date",
            "apply_order",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    norm_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("norm.id", ondelete="CASCADE"), nullable=False
    )
    source_document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("npa_document.id", ondelete="CASCADE"), nullable=False
    )

    event_type: Mapped[NormEventType] = mapped_column(
        Enum(NormEventType, name="norm_event_type"), nullable=False
    )
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    apply_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    operation_type: Mapped[OperationType] = mapped_column(
        Enum(OperationType, name="operation_type"), nullable=False
    )
    unit_address: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    text_before: Mapped[str | None] = mapped_column(Text)
    text_after: Mapped[str | None] = mapped_column(Text)

    apply_kind: Mapped[ApplyKind] = mapped_column(
        Enum(ApplyKind, name="apply_kind"), nullable=False
    )
    apply_status: Mapped[ApplyStatus] = mapped_column(
        Enum(ApplyStatus, name="apply_status"),
        nullable=False,
        default=ApplyStatus.needs_manual,
    )

    raw_reference_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("npa_raw.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    norm: Mapped["Norm"] = relationship(back_populates="change_events")


class NormRevisionCache(Base):
    """Собранная редакция — ПРОИЗВОДНОЕ, кэш."""

    __tablename__ = "norm_revision_cache"
    __table_args__ = (
        UniqueConstraint("norm_id", "as_of_date", name="uq_norm_revision_cache_norm_date"),
        Index("ix_norm_revision_cache_invalidated", "invalidated_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    norm_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("norm.id", ondelete="CASCADE"), nullable=False
    )

    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    assembled_text: Mapped[str] = mapped_column(Text, nullable=False)
    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    norm: Mapped["Norm"] = relationship(back_populates="revision_caches")


# ---------------------------------------------------------------------------
# Наблюдаемость конвейера (§11)
# ---------------------------------------------------------------------------


class PipelineRun(Base):
    """Журнал запусков конвейера — метрики сбора и обработки."""

    __tablename__ = "pipeline_run"
    __table_args__ = (
        Index("ix_pipeline_run_job_type", "job_type"),
        Index("ix_pipeline_run_started_at", "started_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_type: Mapped[PipelineJobType] = mapped_column(
        Enum(PipelineJobType, name="pipeline_job_type"), nullable=False
    )
    status: Mapped[PipelineRunStatus] = mapped_column(
        Enum(PipelineRunStatus, name="pipeline_run_status"), nullable=False
    )
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

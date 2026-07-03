"""initial schema — все таблицы Шага 1 (разделы 5–6 ТЗ)

Revision ID: 001
Revises:
Create Date: 2026-06-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- enums ---
    raw_file_type = postgresql.ENUM(
        "pdf", "zip", "svg", "page_snapshot", name="raw_file_type", create_type=False
    )
    relation_type = postgresql.ENUM(
        "amends", "repeals", "supplements", "references", name="relation_type", create_type=False
    )
    delta_completeness = postgresql.ENUM("full", "partial", name="delta_completeness", create_type=False)
    model_route = postgresql.ENUM("qwen", "gateway", name="model_route", create_type=False)
    gate_status = postgresql.ENUM(
        "pending", "passed", "flagged", "rejected", name="gate_status", create_type=False
    )
    missing_act_status = postgresql.ENUM(
        "pending", "fetched", "failed", name="missing_act_status", create_type=False
    )
    post_type = postgresql.ENUM(
        "digest", "single", "enactment_week", "mini_digest", "analysis",
        name="post_type", create_type=False,
    )
    post_status = postgresql.ENUM(
        "draft", "ready", "published", "rejected", name="post_status", create_type=False
    )
    norm_event_type = postgresql.ENUM("baseline", "amendment", name="norm_event_type", create_type=False)
    operation_type = postgresql.ENUM(
        "replace", "supplement", "delete", "full_redaction", name="operation_type", create_type=False
    )
    apply_kind = postgresql.ENUM(
        "full_redaction", "address_patch", name="apply_kind", create_type=False
    )
    apply_status = postgresql.ENUM(
        "applied", "needs_manual", "failed", name="apply_status", create_type=False
    )
    text_extraction_method = postgresql.ENUM(
        "pdf_text", "ocr", name="text_extraction_method", create_type=False
    )

    for enum in (
        raw_file_type, relation_type, delta_completeness, model_route, gate_status,
        missing_act_status, post_type, post_status, norm_event_type, operation_type,
        apply_kind, apply_status, text_extraction_method,
    ):
        enum.create(op.get_bind(), checkfirst=True)

    # --- справочники API ---
    op.create_table(
        "ref_public_block",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "ref_document_type",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "ref_signatory_authority",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- sector_dict ---
    op.create_table(
        "sector_dict",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("parent_code", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["parent_code"], ["sector_dict.code"]),
        sa.PrimaryKeyConstraint("code"),
    )

    # --- npa_document ---
    op.create_table(
        "npa_document",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("eo_number", sa.String(length=64), nullable=False),
        sa.Column("number", sa.String(length=64), nullable=True),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("complex_name", sa.Text(), nullable=True),
        sa.Column("publish_date_short", sa.Date(), nullable=True),
        sa.Column("view_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("document_type_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("signatory_authority_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pages_count", sa.Integer(), nullable=True),
        sa.Column("pdf_file_length", sa.BigInteger(), nullable=True),
        sa.Column("has_svg", sa.Boolean(), nullable=True),
        sa.Column("zip_file_length", sa.BigInteger(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("api_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("significance_score", sa.Float(), nullable=True),
        sa.Column("included_in_post", sa.Boolean(), nullable=True),
        sa.Column("act_group_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_type_id"], ["ref_document_type.id"]),
        sa.ForeignKeyConstraint(["signatory_authority_id"], ["ref_signatory_authority.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("eo_number"),
    )
    op.create_index("ix_npa_document_discovered_at", "npa_document", ["discovered_at"])
    op.create_index("ix_npa_document_publish_date", "npa_document", ["publish_date_short"])
    op.create_index("ix_npa_document_act_group", "npa_document", ["act_group_id"])

    # --- npa_raw ---
    op.create_table(
        "npa_raw",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("raw_type", raw_file_type, nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["npa_document.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_npa_raw_document_id", "npa_raw", ["document_id"])

    # --- npa_text ---
    op.create_table(
        "npa_text",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("full_text", sa.Text(), nullable=False),
        sa.Column("extraction_method", text_extraction_method, nullable=False),
        sa.Column("extracted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("page_count_extracted", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["npa_document.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id"),
    )

    # --- npa_enactment ---
    op.create_table(
        "npa_enactment",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("unit_address", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("conditions", sa.Text(), nullable=True),
        sa.Column("text_fragment", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["npa_document.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_npa_enactment_document_id", "npa_enactment", ["document_id"])

    # --- npa_relation ---
    op.create_table(
        "npa_relation",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_document_id", sa.BigInteger(), nullable=False),
        sa.Column("target_act_identifier", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("target_document_id", sa.BigInteger(), nullable=True),
        sa.Column("relation_type", relation_type, nullable=False),
        sa.Column("target_name_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["source_document_id"], ["npa_document.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_document_id"], ["npa_document.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_npa_relation_source", "npa_relation", ["source_document_id"])
    op.create_index("ix_npa_relation_target_doc", "npa_relation", ["target_document_id"])

    # --- npa_delta ---
    op.create_table(
        "npa_delta",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("completeness_status", delta_completeness, nullable=False),
        sa.Column("delta_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("impact_description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["npa_document.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id"),
    )

    # --- npa_sector ---
    op.create_table(
        "npa_sector",
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("sector_code", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["npa_document.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sector_code"], ["sector_dict.code"]),
        sa.PrimaryKeyConstraint("document_id", "sector_code"),
    )

    # --- npa_summary ---
    op.create_table(
        "npa_summary",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("model_route", model_route, nullable=False),
        sa.Column("gate_status", gate_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["npa_document.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_npa_summary_document_id", "npa_summary", ["document_id"])

    # --- missing_acts_queue ---
    op.create_table(
        "missing_acts_queue",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("referenced_act_identifier", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("referencing_document_id", sa.BigInteger(), nullable=False),
        sa.Column("status", missing_act_status, nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["referencing_document_id"], ["npa_document.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_missing_acts_status", "missing_acts_queue", ["status"])
    op.create_index(
        "ix_missing_acts_identifier",
        "missing_acts_queue",
        ["referenced_act_identifier"],
        postgresql_using="gin",
    )

    # --- post_bank ---
    op.create_table(
        "post_bank",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("post_type", post_type, nullable=False),
        sa.Column("status", post_status, nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_post_bank_status", "post_bank", ["status"])

    # --- post_item ---
    op.create_table(
        "post_item",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("post_id", sa.BigInteger(), nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["npa_document.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["post_id"], ["post_bank.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("post_id", "document_id", name="uq_post_item_post_document"),
    )
    op.create_index("ix_post_item_post_id", "post_item", ["post_id"])

    # --- gate_flag ---
    op.create_table(
        "gate_flag",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=True),
        sa.Column("summary_id", sa.BigInteger(), nullable=True),
        sa.Column("gate_number", sa.Integer(), nullable=False),
        sa.Column("flag_type", sa.String(length=128), nullable=False),
        sa.Column("flag_details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["npa_document.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["summary_id"], ["npa_summary.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gate_flag_document_id", "gate_flag", ["document_id"])
    op.create_index("ix_gate_flag_resolved", "gate_flag", ["resolved"])

    # --- norm ---
    op.create_table(
        "norm",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stable_norm_id", sa.String(length=128), nullable=False),
        sa.Column("parent_act_identifier", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("unit_address", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stable_norm_id"),
    )
    op.create_index(
        "ix_norm_parent_act",
        "norm",
        ["parent_act_identifier"],
        postgresql_using="gin",
    )

    # --- norm_change_event ---
    op.create_table(
        "norm_change_event",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("norm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_document_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", norm_event_type, nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("apply_order", sa.Integer(), nullable=False),
        sa.Column("operation_type", operation_type, nullable=False),
        sa.Column("unit_address", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("text_before", sa.Text(), nullable=True),
        sa.Column("text_after", sa.Text(), nullable=True),
        sa.Column("apply_kind", apply_kind, nullable=False),
        sa.Column("apply_status", apply_status, nullable=False),
        sa.Column("raw_reference_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["norm_id"], ["norm.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["raw_reference_id"], ["npa_raw.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_document_id"], ["npa_document.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_norm_change_event_norm_id", "norm_change_event", ["norm_id"])
    op.create_index("ix_norm_change_event_effective_date", "norm_change_event", ["effective_date"])
    op.create_index(
        "ix_norm_change_event_order",
        "norm_change_event",
        ["norm_id", "effective_date", "apply_order"],
    )

    # --- norm_revision_cache ---
    op.create_table(
        "norm_revision_cache",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("norm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("assembled_text", sa.Text(), nullable=False),
        sa.Column("cached_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["norm_id"], ["norm.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("norm_id", "as_of_date", name="uq_norm_revision_cache_norm_date"),
    )
    op.create_index("ix_norm_revision_cache_invalidated", "norm_revision_cache", ["invalidated_at"])


def downgrade() -> None:
    op.drop_table("norm_revision_cache")
    op.drop_table("norm_change_event")
    op.drop_table("norm")
    op.drop_table("gate_flag")
    op.drop_table("post_item")
    op.drop_table("post_bank")
    op.drop_table("missing_acts_queue")
    op.drop_table("npa_summary")
    op.drop_table("npa_sector")
    op.drop_table("npa_delta")
    op.drop_table("npa_relation")
    op.drop_table("npa_enactment")
    op.drop_table("npa_text")
    op.drop_table("npa_raw")
    op.drop_table("npa_document")
    op.drop_table("sector_dict")
    op.drop_table("ref_signatory_authority")
    op.drop_table("ref_document_type")
    op.drop_table("ref_public_block")

    for enum_name in (
        "text_extraction_method", "apply_status", "apply_kind", "operation_type",
        "norm_event_type", "post_status", "post_type", "missing_act_status",
        "gate_status", "model_route", "delta_completeness", "relation_type", "raw_file_type",
    ):
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)

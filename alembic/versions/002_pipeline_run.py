"""pipeline_run — журнал запусков конвейера (§11)

Revision ID: 002
Revises: 001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    job_type = postgresql.ENUM(
        "collect",
        "process",
        "gate",
        "publish",
        "fetch_missing",
        "daily",
        name="pipeline_job_type",
        create_type=False,
    )
    run_status = postgresql.ENUM(
        "success",
        "partial",
        "failed",
        name="pipeline_run_status",
        create_type=False,
    )
    job_type.create(op.get_bind(), checkfirst=True)
    run_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "pipeline_run",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_type", job_type, nullable=False),
        sa.Column("status", run_status, nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pipeline_run_job_type", "pipeline_run", ["job_type"])
    op.create_index("ix_pipeline_run_started_at", "pipeline_run", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_pipeline_run_started_at", table_name="pipeline_run")
    op.drop_index("ix_pipeline_run_job_type", table_name="pipeline_run")
    op.drop_table("pipeline_run")
    op.execute("DROP TYPE IF EXISTS pipeline_run_status")
    op.execute("DROP TYPE IF EXISTS pipeline_job_type")

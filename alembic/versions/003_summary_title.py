"""npa_summary.title — короткий заголовок карточки от Gateway (fix_report_v1, п.9.3)

Revision ID: 003
Revises: 002
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("npa_summary", sa.Column("title", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("npa_summary", "title")

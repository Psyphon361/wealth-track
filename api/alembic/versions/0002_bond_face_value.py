"""bonds: add face_value (per unit)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-24
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("bonds", sa.Column("face_value", sa.Numeric(14, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("bonds", "face_value")

"""users.full_name: optional display name

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-08
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("full_name", sa.String(length=80), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "full_name")

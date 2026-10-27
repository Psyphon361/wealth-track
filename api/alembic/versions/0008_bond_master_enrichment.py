"""bond_master enrichment: issue date/price, rating, source tags

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-27
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("bond_master", sa.Column("issue_date", sa.Date(), nullable=True))
    op.add_column("bond_master", sa.Column("issue_price", sa.Numeric(14, 2), nullable=True))
    op.add_column("bond_master", sa.Column("rating", sa.String(100), nullable=True))
    op.add_column("bond_master", sa.Column("rating_agency", sa.String(100), nullable=True))
    op.add_column("bond_master", sa.Column("rating_as_of", sa.Date(), nullable=True))
    op.add_column(
        "bond_master",
        sa.Column(
            "sources",
            postgresql.ARRAY(sa.String(20)),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
    )


def downgrade() -> None:
    op.drop_column("bond_master", "sources")
    op.drop_column("bond_master", "rating_as_of")
    op.drop_column("bond_master", "rating_agency")
    op.drop_column("bond_master", "rating")
    op.drop_column("bond_master", "issue_price")
    op.drop_column("bond_master", "issue_date")

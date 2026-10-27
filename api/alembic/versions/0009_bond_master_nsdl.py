"""bond_master NSDL fields: coupon type, interest frequency, issue size, ownership, issue mode

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-27
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("bond_master", sa.Column("coupon_type", sa.String(20), nullable=True))
    op.add_column("bond_master", sa.Column("interest_frequency", sa.String(20), nullable=True))
    op.add_column("bond_master", sa.Column("issue_size", sa.Numeric(18, 2), nullable=True))
    op.add_column("bond_master", sa.Column("issuer_ownership", sa.String(10), nullable=True))
    op.add_column("bond_master", sa.Column("issue_mode", sa.String(10), nullable=True))
    op.add_column("bond_master", sa.Column("is_perpetual", sa.Boolean(), nullable=True))
    op.add_column("bond_master", sa.Column("nsdl_status", sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column("bond_master", "nsdl_status")
    op.drop_column("bond_master", "is_perpetual")
    op.drop_column("bond_master", "issue_mode")
    op.drop_column("bond_master", "issuer_ownership")
    op.drop_column("bond_master", "issue_size")
    op.drop_column("bond_master", "interest_frequency")
    op.drop_column("bond_master", "coupon_type")

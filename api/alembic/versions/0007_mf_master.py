"""rename mf_schemes to mf_master (matches stock_master / bond_master)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-26
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE mf_schemes RENAME TO mf_master")
    op.execute("ALTER TABLE mf_master RENAME CONSTRAINT mf_schemes_pkey TO mf_master_pkey")
    op.execute("ALTER INDEX ix_mf_schemes_name_trgm RENAME TO ix_mf_master_name_trgm")


def downgrade() -> None:
    op.execute("ALTER INDEX ix_mf_master_name_trgm RENAME TO ix_mf_schemes_name_trgm")
    op.execute("ALTER TABLE mf_master RENAME CONSTRAINT mf_master_pkey TO mf_schemes_pkey")
    op.execute("ALTER TABLE mf_master RENAME TO mf_schemes")

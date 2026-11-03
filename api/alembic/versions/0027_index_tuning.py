"""index tuning: drop redundant user_id indexes, trigram indexes the master searches can use

The ten single-column (user_id) indexes on the holding tables are a left prefix of
(user_id, deleted_at) from 0025/0026, so they are dropped.

The stock, bond and MF searches filter with `col ILIKE '%token%'` OR-ed across several
columns. The old trigram indexes on lower(name) cannot serve that (wrong expression, and a
BitmapOr needs every OR arm indexed), so they were never used. Each is replaced by one
multi-column trigram GIN index over exactly the columns the search ORs together.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-03
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HOLDING_TABLES = (
    "fixed_deposits",
    "recurring_deposits",
    "stocks",
    "bonds",
    "mutual_funds",
    "nps_holdings",
    "gold_holdings",
    "cash_holdings",
    "pf_holdings",
    "other_holdings",
)

# table -> columns OR-ed together by its search (stock_master.search_stocks,
# bond_master.search_bonds, amfi.search_schemes)
SEARCH_COLUMNS = {
    "stock_master": ("name", "nse_symbol", "bse_symbol", "bse_code", "isin"),
    "bond_master": ("name", "nse_symbol", "isin", "issuer"),
    "mf_master": ("name", "amc", "plan", "option"),
}


def upgrade() -> None:
    for table in HOLDING_TABLES:
        op.drop_index(f"ix_{table}_user_id", table_name=table)
    for table, columns in SEARCH_COLUMNS.items():
        op.execute(f"DROP INDEX ix_{table}_name_trgm")
        ops = ", ".join(f"{column} gin_trgm_ops" for column in columns)
        op.execute(f"CREATE INDEX ix_{table}_search_trgm ON {table} USING gin ({ops})")


def downgrade() -> None:
    for table in SEARCH_COLUMNS:
        op.execute(f"DROP INDEX ix_{table}_search_trgm")
        op.execute(
            f"CREATE INDEX ix_{table}_name_trgm ON {table} USING gin (lower(name) gin_trgm_ops)"
        )
    for table in HOLDING_TABLES:
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])

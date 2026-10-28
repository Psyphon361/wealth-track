"""users, refresh tokens, login attempts; holdings.user_id

Existing holdings are assigned to OWNER_EMAIL (env var, or owner_email in api/.env).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-28
"""
import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HOLDINGS_TABLES = ("fixed_deposits", "recurring_deposits", "stocks", "bonds", "mutual_funds")
_EMAIL_RE = re.compile(r"^[^@\s'\":\\]+@[^@\s'\":\\]+$")


def _owner_email() -> str | None:
    value = os.environ.get("OWNER_EMAIL")
    if not value:
        from app.config import settings

        value = settings.owner_email
    value = (value or "").strip().lower()
    if not value:
        return None
    if not _EMAIL_RE.match(value):
        raise RuntimeError("OWNER_EMAIL is not a valid email address")
    return value


def _assign_owner(owner: str) -> None:
    literal = "'" + owner.replace("'", "''") + "'"
    op.execute(
        sa.text(
            f"INSERT INTO users (email, is_active) SELECT {literal}, true "
            f"WHERE NOT EXISTS (SELECT 1 FROM users WHERE email = {literal})"
        )
    )
    for table in HOLDINGS_TABLES:
        op.execute(
            sa.text(f"UPDATE {table} SET user_id = (SELECT id FROM users WHERE email = {literal})")
        )


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("family_id", sa.String(36), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_login_attempts_email", "login_attempts", ["email"])
    op.create_index("ix_login_attempts_attempted_at", "login_attempts", ["attempted_at"])

    for table in HOLDINGS_TABLES:
        op.add_column(table, sa.Column("user_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_user_id", table, "users", ["user_id"], ["id"], ondelete="CASCADE"
        )
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])

    owner = _owner_email()
    if context.is_offline_mode():
        if owner:
            _assign_owner(owner)
        else:
            op.execute("-- OWNER_EMAIL not set: assuming no holdings rows exist (offline mode cannot check)")
    else:
        bind = op.get_bind()
        has_rows = any(
            bind.execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")).scalar()
            for table in HOLDINGS_TABLES
        )
        if has_rows:
            if not owner:
                raise RuntimeError("Set OWNER_EMAIL to assign existing holdings")
            _assign_owner(owner)

    for table in HOLDINGS_TABLES:
        op.alter_column(table, "user_id", existing_type=sa.Integer(), nullable=False)


def downgrade() -> None:
    for table in reversed(HOLDINGS_TABLES):
        op.drop_index(f"ix_{table}_user_id", table_name=table)
        op.drop_constraint(f"fk_{table}_user_id", table, type_="foreignkey")
        op.drop_column(table, "user_id")
    op.drop_index("ix_login_attempts_attempted_at", table_name="login_attempts")
    op.drop_index("ix_login_attempts_email", table_name="login_attempts")
    op.drop_table("login_attempts")
    op.drop_index("ix_refresh_tokens_family_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_table("users")

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import str_enum


class HoldingFunding(Base):
    """Money a new holding was paid for out of a Cash & Savings account ("Paid from").

    The amount was taken off the account's balance when the holding was added. holding_id points at
    one of several tables (asset_type says which), so it has no foreign key. Deleting the holding
    refunds the account (refunded_at set); restoring it takes the money out again (cleared).
    `from_exit_id` is the sale or settlement whose proceeds this money came from, if any.
    """

    __tablename__ = "holding_fundings"
    __table_args__ = (
        Index("ix_holding_fundings_user_type_holding", "user_id", "asset_type", "holding_id"),
        # A holding is paid for from one account at a time (refunded rows stay as history).
        Index(
            "uq_holding_fundings_active",
            "asset_type",
            "holding_id",
            unique=True,
            postgresql_where=text("refunded_at IS NULL"),
            sqlite_where=text("refunded_at IS NULL"),
        ),
        CheckConstraint("amount > 0", name="ck_holding_fundings_amount_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    asset_type: Mapped[str] = mapped_column(
        str_enum(
            "fd", "rd", "stock", "bond", "mf", "nps", "gold", "cash", "pf", "other",
            name="holding_funding_asset_type",
        )  # fmt: skip
    )
    holding_id: Mapped[int]
    cash_holding_id: Mapped[int | None] = mapped_column(
        ForeignKey("cash_holdings.id", ondelete="SET NULL")
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    funded_on: Mapped[date]
    from_exit_id: Mapped[int | None] = mapped_column(
        ForeignKey("holding_exits.id", ondelete="SET NULL")
    )
    # The account's balance date before this debit (kept for the record).
    prev_balance_date: Mapped[date]
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

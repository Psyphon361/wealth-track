from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampedMixin, str_enum


class Cash(TimestampedMixin, Base):
    __tablename__ = "cash_holdings"
    _checks = (
        CheckConstraint("balance >= 0", name="ck_cash_holdings_balance_nonnegative"),
        CheckConstraint(
            "interest_rate IS NULL OR (interest_rate >= 0 AND interest_rate <= 100)",
            name="ck_cash_holdings_rate_range",
        ),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(
        str_enum("savings", "current", "cash", "other", name="cash_kind")
    )
    balance: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    interest_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    balance_date: Mapped[date]

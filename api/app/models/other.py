from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampedMixin


class Other(TimestampedMixin, Base):
    __tablename__ = "other_holdings"
    _checks = (
        CheckConstraint("current_value >= 0", name="ck_other_holdings_value_nonnegative"),
        CheckConstraint(
            "invested_amount IS NULL OR invested_amount >= 0",
            name="ck_other_holdings_invested_nonnegative",
        ),
        CheckConstraint(
            "acquired_on IS NULL OR acquired_on <= value_date",
            name="ck_other_holdings_acquired_before_value",
        ),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(40))
    current_value: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    value_date: Mapped[date]
    invested_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    acquired_on: Mapped[date | None]
    # Set when the holding is sold; the row stays (status "sold").
    closed_on: Mapped[date | None]

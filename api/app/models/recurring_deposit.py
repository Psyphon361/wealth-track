from datetime import date
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import COMPOUNDING_VALUES, TimestampedMixin, str_enum


class RecurringDeposit(TimestampedMixin, Base):
    __tablename__ = "recurring_deposits"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    bank: Mapped[str] = mapped_column(String(200))
    label: Mapped[str | None] = mapped_column(String(200))
    monthly_instalment: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    rate: Mapped[Decimal] = mapped_column(Numeric(6, 3))
    start_date: Mapped[date]
    tenure_years: Mapped[int] = mapped_column(default=0, server_default="0")
    tenure_months: Mapped[int] = mapped_column(default=0, server_default="0")
    tenure_days: Mapped[int] = mapped_column(default=0, server_default="0")
    compounding: Mapped[str] = mapped_column(
        str_enum(*COMPOUNDING_VALUES, name="rd_compounding"),
        default="quarterly",
        server_default="quarterly",
    )

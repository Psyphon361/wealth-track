from datetime import date
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampedMixin


class Other(TimestampedMixin, Base):
    __tablename__ = "other_holdings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(40))
    current_value: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    value_date: Mapped[date]
    invested_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    acquired_on: Mapped[date | None]

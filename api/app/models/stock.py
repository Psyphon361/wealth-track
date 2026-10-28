from datetime import date
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampedMixin, str_enum


class Stock(TimestampedMixin, Base):
    __tablename__ = "stocks"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    symbol: Mapped[str | None] = mapped_column(String(50))
    exchange: Mapped[str] = mapped_column(
        str_enum("NSE", "BSE", name="stock_exchange"),
        default="NSE",
        server_default="NSE",
    )
    master_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_master.id", ondelete="SET NULL")
    )
    broker: Mapped[str | None] = mapped_column(String(200))
    quantity: Mapped[int]
    avg_buy_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    buy_date: Mapped[date]

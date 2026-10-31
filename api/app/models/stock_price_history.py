from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class StockPriceHistory(Base):
    """Daily close per held stock_master row (appended by the securities import, month-end backfill)."""

    __tablename__ = "stock_price_history"

    master_id: Mapped[int] = mapped_column(
        ForeignKey("stock_master.id", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    close: Mapped[Decimal] = mapped_column(Numeric(14, 2))


class StockPriceHistorySync(Base):
    """Stocks whose 12-month month-end backfill has been done."""

    __tablename__ = "stock_price_history_sync"

    master_id: Mapped[int] = mapped_column(
        ForeignKey("stock_master.id", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )
    backfilled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

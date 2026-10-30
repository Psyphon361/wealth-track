from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class StockPriceLatest(Base):
    """Last known price per stock_master row ('yahoo' live quote or 'bhavcopy' daily close)."""

    __tablename__ = "stock_price_latest"

    master_id: Mapped[int] = mapped_column(
        ForeignKey("stock_master.id", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )
    # NULL price = only a failed fetch attempt is recorded (backoff); such rows are ignored.
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    prev_close: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    price_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(20))
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

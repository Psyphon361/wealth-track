from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import str_enum


class StockMaster(Base):
    """Listed stocks and ETFs (NSE + BSE), refreshed from exchange files.

    The trigram index covers exactly the columns search_stocks ORs together (ILIKE), so the
    planner can use a BitmapOr over it (migration 0027).
    """

    __tablename__ = "stock_master"
    __table_args__ = (
        Index(
            "ix_stock_master_search_trgm",
            "name", "nse_symbol", "bse_symbol", "bse_code", "isin",
            postgresql_using="gin",
            postgresql_ops={
                c: "gin_trgm_ops" for c in ("name", "nse_symbol", "bse_symbol", "bse_code", "isin")
            },
        ),
    )  # fmt: skip

    id: Mapped[int] = mapped_column(primary_key=True)
    isin: Mapped[str] = mapped_column(String(12), unique=True)
    kind: Mapped[str] = mapped_column(str_enum("stock", "etf", name="stock_master_kind"))
    name: Mapped[str] = mapped_column(String(300))
    nse_symbol: Mapped[str | None] = mapped_column(String(50))
    nse_series: Mapped[str | None] = mapped_column(String(10))
    bse_code: Mapped[str | None] = mapped_column(String(10))
    bse_symbol: Mapped[str | None] = mapped_column(String(50))
    bse_group: Mapped[str | None] = mapped_column(String(10))
    face_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen: Mapped[date | None]
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

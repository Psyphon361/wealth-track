from datetime import date
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampedMixin, str_enum


class Gold(TimestampedMixin, Base):
    """Gold or silver holding (metal gold|silver); table name kept as gold_holdings."""

    __tablename__ = "gold_holdings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    form: Mapped[str] = mapped_column(
        str_enum("jewellery", "coin", "bar", "digital", name="gold_form")
    )
    metal: Mapped[str] = mapped_column(
        str_enum("gold", "silver", name="gold_metal"), default="gold", server_default="gold"
    )
    purity: Mapped[str] = mapped_column(
        str_enum("999", "995", "916", "750", "585", "925", name="gold_purity")
    )
    weight_grams: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    purchase_date: Mapped[date]
    invested_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))

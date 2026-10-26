from datetime import date
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampedMixin, str_enum


class Bond(TimestampedMixin, Base):
    __tablename__ = "bonds"

    name: Mapped[str] = mapped_column(String(200))
    isin: Mapped[str | None] = mapped_column(String(20))
    issuer: Mapped[str] = mapped_column(String(200))
    bond_type: Mapped[str] = mapped_column(
        str_enum("government", "corporate", "tax_free", "sgb", "other", name="bond_type")
    )
    master_id: Mapped[int | None] = mapped_column(
        ForeignKey("bond_master.id", ondelete="SET NULL")
    )
    platform: Mapped[str | None] = mapped_column(String(200))
    quantity: Mapped[int]
    face_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    purchase_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    purchase_date: Mapped[date]
    ytm: Mapped[Decimal] = mapped_column(Numeric(6, 3))
    maturity_date: Mapped[date]

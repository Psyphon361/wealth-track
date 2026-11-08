from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampedMixin, str_enum


class Bond(TimestampedMixin, Base):
    __tablename__ = "bonds"
    _checks = (
        CheckConstraint("quantity > 0", name="ck_bonds_quantity_positive"),
        CheckConstraint("purchase_price > 0", name="ck_bonds_purchase_price_positive"),
        CheckConstraint("invested_amount >= 0", name="ck_bonds_invested_nonnegative"),
        CheckConstraint(
            "face_value IS NULL OR face_value > 0", name="ck_bonds_face_value_positive"
        ),
        CheckConstraint("maturity_date > purchase_date", name="ck_bonds_maturity_after_purchase"),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
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
    invested_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    purchase_date: Mapped[date]
    ytm: Mapped[Decimal] = mapped_column(Numeric(6, 3))
    maturity_date: Mapped[date]
    # Set when the whole holding is sold before maturity; the row stays (status "sold").
    closed_on: Mapped[date | None]

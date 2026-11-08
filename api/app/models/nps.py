from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampedMixin
from app.models.nps_master import NpsMaster


class Nps(TimestampedMixin, Base):
    __tablename__ = "nps_holdings"
    _checks = (
        CheckConstraint("units > 0", name="ck_nps_holdings_units_positive"),
        CheckConstraint("contributed >= 0", name="ck_nps_holdings_contributed_nonnegative"),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    scheme_id: Mapped[str] = mapped_column(String(20), ForeignKey("nps_master.scheme_id"))
    units: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    contributed: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    start_date: Mapped[date]

    master: Mapped[NpsMaster] = relationship(lazy="joined")

    # Scheme fields come from the master row, so the grid, search and filters can use them.
    @property
    def scheme_name(self) -> str:
        return self.master.scheme_name

    @property
    def pfm_name(self) -> str:
        return self.master.pfm_name

    @property
    def tier(self) -> str | None:
        return self.master.tier

    @property
    def asset_class(self) -> str:
        return self.master.asset_class

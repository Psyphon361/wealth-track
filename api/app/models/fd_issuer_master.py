from datetime import date, datetime

from sqlalchemy import JSON, ARRAY, Boolean, DateTime, ForeignKey, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import str_enum

CATEGORIES = (
    "public_sector", "private_sector", "small_finance", "foreign", "regional_rural",
    "local_area", "payments", "state_coop", "district_coop", "urban_coop", "nbfc", "hfc",
    "post_office",
)  # fmt: skip


class FdIssuerMaster(Base):
    """Banks, NBFCs, HFCs and India Post that take FDs/RDs, refreshed from RBI/DICGC-derived lists.

    The trigram index on lower(name) is created in migration 0011 (expression index with
    operator class, so it is not declared here).
    """

    __tablename__ = "fd_issuer_master"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(300))
    short_name: Mapped[str | None] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(str_enum(*CATEGORIES, name="fd_issuer_category"))
    regulator: Mapped[str | None] = mapped_column(String(10))
    reg_no: Mapped[str | None] = mapped_column(String(40))
    dicgc_insured: Mapped[bool | None] = mapped_column(Boolean)
    accepts_deposits: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    merged_into_id: Mapped[int | None] = mapped_column(
        ForeignKey("fd_issuer_master.id", ondelete="SET NULL")
    )
    merged_on: Mapped[date | None]
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_seen: Mapped[date | None]
    sources: Mapped[list[str]] = mapped_column(
        ARRAY(String(20)).with_variant(JSON(), "sqlite"),
        default=list,
        server_default=text("'{}'"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    merged_into: Mapped["FdIssuerMaster | None"] = relationship(
        remote_side=[id], lazy="joined"
    )

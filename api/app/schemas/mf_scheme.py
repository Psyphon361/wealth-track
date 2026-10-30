from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.assets import Dec


class MFSchemeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    scheme_code: int
    name: str
    amc: str | None = None
    plan: str | None = None
    option: str | None = None
    idcw_frequency: str | None = None
    amfi_category: str | None = None
    category: str
    nav: Dec | None = None
    nav_date: date | None = None
    isin_growth_payout: str | None = None
    isin_reinvest: str | None = None


class AmfiImportResult(BaseModel):
    rows: int
    active: int
    inactive: int
    file_date: date | None = None
    inserted: int
    updated: int
    unchanged: int
    deactivated: int
    navs_upserted: int
    history_appended: int = 0
    history_synced: int = 0


class MFNavOnDate(BaseModel):
    scheme_code: int
    requested_date: date
    nav_date: date
    nav: Dec
    source: Literal["latest", "history"]

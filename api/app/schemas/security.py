from datetime import date

from pydantic import BaseModel, ConfigDict

from app.schemas.assets import Dec


class SecurityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    isin: str
    kind: str
    name: str
    nse_symbol: str | None = None
    nse_series: str | None = None
    bse_code: str | None = None
    bse_symbol: str | None = None
    bse_group: str | None = None
    face_value: Dec | None = None
    coupon_rate: Dec | None = None
    maturity_date: date | None = None
    issuer: str | None = None
    bond_type: str | None = None
    is_active: bool


class SecuritiesImportResult(BaseModel):
    sources: dict[str, int]
    kinds: dict[str, int]
    total: int
    inserted: int
    updated: int
    unchanged: int
    deactivated: int
    skipped: int
    last_seen_refreshed: int = 0
    bhav_date: date | None = None
    bse_date: date | None = None
    bhav_error: str | None = None
    bse_error: str | None = None

from datetime import date

from pydantic import BaseModel, ConfigDict

from app.schemas.assets import Dec


class StockMasterRead(BaseModel):
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
    is_active: bool


class BondMasterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    isin: str
    name: str
    issuer: str | None = None
    nse_symbol: str | None = None
    nse_series: str | None = None
    face_value: Dec | None = None
    coupon_rate: Dec | None = None
    maturity_date: date | None = None
    bond_type: str
    issue_date: date | None = None
    issue_price: Dec | None = None
    rating: str | None = None
    rating_agency: str | None = None
    rating_as_of: date | None = None
    coupon_type: str | None = None
    interest_frequency: str | None = None
    issue_size: Dec | None = None
    issuer_ownership: str | None = None
    issue_mode: str | None = None
    is_perpetual: bool | None = None
    nsdl_status: str | None = None
    is_active: bool


class StockImportResult(BaseModel):
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


class BondImportResult(BaseModel):
    sources: dict[str, int]
    total: int
    inserted: int
    updated: int
    unchanged: int
    deactivated: int
    skipped: int
    last_seen_refreshed: int = 0
    excluded: int = 0  # Social Stock Exchange instruments left out
    with_rating: int = 0
    nsdl_only: int = 0  # rows seen only in the NSDL list
    bhav_date: date | None = None
    bhav_error: str | None = None
    errors: dict[str, str] = {}  # optional/seed sources that failed or were missing


class FdIssuerRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class FdIssuerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    short_name: str | None = None
    category: str
    regulator: str | None = None
    reg_no: str | None = None
    dicgc_insured: bool | None = None
    accepts_deposits: bool
    merged_into: FdIssuerRef | None = None
    merged_on: date | None = None
    is_active: bool


class FdIssuerImportResult(BaseModel):
    total: int
    inserted: int
    updated: int
    unchanged: int
    deactivated: int
    last_seen_refreshed: int = 0
    merge_links_updated: int = 0
    skipped: int = 0
    by_category: dict[str, int]
    by_source: dict[str, int]
    dicgc_names: int = 0
    dicgc_matched: int = 0
    dicgc_unmatched: int = 0
    dicgc_unclaimed: int = 0
    dicgc_only: int = 0
    unmatched_names: dict[str, list[str]] = {}
    unclaimed_names: list[str] = []
    errors: dict[str, str] = {}  # sources that failed or were missing
    notes: list[str] = []


class MarketImportResult(BaseModel):
    stocks: StockImportResult
    bonds: BondImportResult

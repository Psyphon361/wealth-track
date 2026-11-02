from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel

from app.schemas.assets import Number

AssetType = Literal["fd", "rd", "stock", "bond", "mf", "nps", "gold", "cash", "pf", "other"]
Amount = Annotated[Decimal, Number]


class Totals(BaseModel):
    invested: Amount
    current_value: Amount
    gain: Amount
    gain_pct: Amount


class PortfolioGroup(BaseModel):
    type: AssetType
    label: str
    # Each item: the asset's Read-schema fields plus computed invested,
    # current_value, gain, gain_pct, maturity_date (optional), status, interest_received (payout FDs),
    # nav + nav_date (MF only; null when valued at invested amount).
    items: list[dict[str, Any]]
    totals: Totals
    count: int
    matured_count: int


class PortfolioResponse(BaseModel):
    groups: list[PortfolioGroup]


class DashboardByType(BaseModel):
    type: AssetType
    label: str
    count: int
    matured_count: int
    invested: Amount
    current: Amount
    gain: Amount | None = None
    gain_pct: Amount | None = None
    # Invested of only the holdings that have a gain: the base for gain_pct and group subtotals.
    gain_base: Amount
    day_change: Amount | None = None
    allocation_pct: Amount


class DashboardResponse(BaseModel):
    total_invested: Amount
    total_current: Amount
    total_gain: Amount
    gain_pct: Amount
    # 1-day change over active market-linked holdings; null when no holding has a figure.
    day_change: Amount | None = None
    day_change_pct: Amount | None = None
    day_change_as_of: date | None = None
    by_type: list[DashboardByType]

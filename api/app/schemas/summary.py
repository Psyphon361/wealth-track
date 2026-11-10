from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel

from app.schemas.assets import Number
from app.schemas.exits import Unsettled

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
    # Closed holdings: matured or sold. matured_count is an alias kept for compatibility.
    matured_count: int
    closed_count: int


class PortfolioResponse(BaseModel):
    groups: list[PortfolioGroup]


class DashboardByType(BaseModel):
    type: AssetType
    label: str
    count: int
    matured_count: int
    closed_count: int
    invested: Amount
    current: Amount
    gain: Amount | None = None
    gain_pct: Amount | None = None
    # Invested of only the holdings that have a gain: the base for gain_pct and group subtotals.
    gain_base: Amount
    day_change: Amount | None = None
    allocation_pct: Amount


class AttentionMaturing(BaseModel):
    type: AssetType
    id: int
    name: str
    date: date
    days_left: int
    amount: Amount | None = None
    approximate: bool
    rate: Amount | None = None


class AttentionStale(BaseModel):
    type: AssetType
    id: int
    name: str
    as_of: date


class AttentionSip(BaseModel):
    id: int
    fund_name: str
    mutual_fund_id: int | None = None
    amount: Amount
    next_date: date


class AttentionCounts(BaseModel):
    maturing: int = 0
    stale: int = 0
    sips: int = 0


class Attention(BaseModel):
    """What needs a look soon: maturities in 30 days, stale hand-entered values, SIPs due in 7
    days. Each list holds at most 20 rows; counts hold the true totals."""

    maturing: list[AttentionMaturing] = []
    stale: list[AttentionStale] = []
    sips: list[AttentionSip] = []
    counts: AttentionCounts = AttentionCounts()


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
    # Matured deposits and bonds whose payout has not been recorded yet.
    unsettled: Unsettled = Unsettled()
    attention: Attention = Attention()

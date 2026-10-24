from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel

from app.schemas.assets import Number

AssetType = Literal["fd", "rd", "stock", "bond", "mf"]
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
    # current_value, gain, gain_pct, maturity_date (optional), status.
    items: list[dict[str, Any]]
    totals: Totals


class PortfolioResponse(BaseModel):
    groups: list[PortfolioGroup]


class DashboardByType(BaseModel):
    type: AssetType
    label: str
    count: int
    invested: Amount
    current: Amount
    allocation_pct: Amount


class DashboardResponse(BaseModel):
    total_invested: Amount
    total_current: Amount
    total_gain: Amount
    gain_pct: Amount
    by_type: list[DashboardByType]

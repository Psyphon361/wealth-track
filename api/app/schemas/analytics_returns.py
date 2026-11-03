from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.schemas.summary import Amount, AssetType

# Shapes returned by app/services/analytics_returns.py. Money and percents are Amount (JSON
# numbers, 2 dp); dates are YYYY-MM-DD.

ReturnBasis = Literal["transactions", "purchase_date", "instalments", "mixed"]


class ReturnGroup(BaseModel):
    key: str  # "overall", a class (equity, debt, ...) or an asset type slug
    label: str
    holdings: int
    invested: Amount
    current: Amount
    gain: Amount
    # XIRR % when annualised, else gain / invested %; null when it can't be computed.
    return_pct: Amount | None
    annualised: bool
    basis: ReturnBasis | None
    since: date  # earliest cash flow


class RankedHolding(BaseModel):
    type: AssetType
    id: int
    name: str
    return_pct: Amount
    gain: Amount


class ReferenceRate(BaseModel):
    type: Literal["pf", "nps"]
    id: int
    name: str
    basis: Literal["interest_rate", "nav_cagr"]
    rate_pct: Amount | None


class ReturnsExcluded(BaseModel):
    at_cost: int
    no_flows: int
    other_without_invested: int


class AnalyticsReturns(BaseModel):
    as_of: date
    overall: ReturnGroup | None
    by_class: list[ReturnGroup]
    by_type: list[ReturnGroup]
    best: list[RankedHolding]
    worst: list[RankedHolding]
    rates: list[ReferenceRate]
    excluded: ReturnsExcluded

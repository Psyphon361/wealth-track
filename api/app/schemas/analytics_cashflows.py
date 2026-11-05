from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel

from app.schemas.assets import Number

Amount = Annotated[Decimal, Number]


class InflowItem(BaseModel):
    date: date
    type: Literal["fd", "rd", "bond"]
    id: int
    name: str
    kind: Literal["coupon", "interest_payout", "maturity", "redemption"]
    interest: Amount
    principal: Amount


class InflowMonth(BaseModel):
    month: str
    interest: Amount
    principal: Amount
    items: list[InflowItem]


class InflowTotals(BaseModel):
    interest: Amount
    principal: Amount


class AnalyticsInflows(BaseModel):
    as_of: date
    months: list[InflowMonth]
    totals: InflowTotals
    types: list[Literal["fd", "rd", "bond"]]

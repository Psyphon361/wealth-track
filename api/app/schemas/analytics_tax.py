from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel

from app.schemas.assets import Number

Amount = Annotated[Decimal, Number]


class TaxFy(BaseModel):
    start_year: int
    label: str
    is_current: bool


class TaxHolding(BaseModel):
    id: int
    type: Literal["fd", "rd"]
    name: str
    interest_to_date: Amount
    interest_projected: Amount


class TaxPayer(BaseModel):
    key: str
    name: str
    kind: Literal["bank", "company"]
    threshold: Amount
    interest_to_date: Amount
    interest_projected: Amount
    crosses: bool
    tds_estimate: Amount
    holdings: list[TaxHolding]


class TaxTotals(BaseModel):
    interest_to_date: Amount
    interest_projected: Amount
    tds_estimate: Amount


class TaxSavings(BaseModel):
    interest_estimate: Amount
    accounts: int


class TaxExcluded(BaseModel):
    bonds: int


class AnalyticsTax(BaseModel):
    fy: str
    fy_start: date
    fy_end: date
    as_of: date
    is_current: bool
    available_fys: list[TaxFy]
    payers: list[TaxPayer]
    totals: TaxTotals
    savings: TaxSavings | None
    excluded: TaxExcluded

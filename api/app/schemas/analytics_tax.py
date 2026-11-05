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


class TaxPayment(BaseModel):
    date: date
    gross: Amount
    tds: Amount
    net: Amount
    paid: bool


class TaxHolding(BaseModel):
    id: int
    type: Literal["fd", "rd", "bond"]
    name: str
    subtitle: str | None = None
    interest_to_date: Amount
    interest_projected: Amount
    tds_estimate: Amount
    payments: list[TaxPayment] | None = None


class TaxByClass(BaseModel):
    type: Literal["fd", "rd", "bond", "savings"]
    label: str
    interest_to_date: Amount
    interest_projected: Amount
    tds_estimate: Amount
    holdings_count: int


class TaxPayer(BaseModel):
    key: str
    name: str
    kind: Literal["bank", "company", "bond"]
    tds_rule: Literal["threshold", "every_payment", "none"]
    threshold: Amount | None
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


class TaxTaxable(BaseModel):
    interest_to_date: Amount
    interest_projected: Amount


class TaxFreeItem(BaseModel):
    kind: Literal["ppf", "epf", "vpf", "tax_free_bond"]
    id: int
    name: str
    interest_to_date: Amount
    interest_projected: Amount


class TaxFree(BaseModel):
    interest_to_date: Amount
    interest_projected: Amount
    items: list[TaxFreeItem]


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
    by_class: list[TaxByClass]
    totals: TaxTotals
    savings: TaxSavings | None
    taxable: TaxTaxable
    tax_free: TaxFree
    excluded: TaxExcluded


class BondPayment(BaseModel):
    date: date
    kind: Literal["coupon", "redemption", "sale"]
    gross: Amount
    tds: Amount
    net: Amount
    fy: str
    paid: bool
    # Redemptions and sales only; True for an SGB (redeems at the gold price) and for every sale.
    estimated_value: bool | None = None


class BondFySummary(BaseModel):
    fy: str
    coupons: int
    gross: Amount
    tds: Amount
    net: Amount


class BondSchedule(BaseModel):
    id: int
    name: str
    issuer: str | None
    bond_type: str
    coupon_rate: Amount | None
    frequency: str | None
    face_value: Amount | None
    quantity: int
    purchase_date: date
    maturity_date: date
    # True when maturity_date is an earlier exit date than the bond's own maturity (bond_maturity_date).
    planned_sale: bool
    bond_maturity_date: date | None
    tds_rate: Amount
    estimated: Literal[True]
    payments: list[BondPayment]
    next_payment: BondPayment | None
    by_fy: list[BondFySummary]


class BondScheduleResponse(BaseModel):
    as_of: date
    bonds: list[BondSchedule]
    excluded: int

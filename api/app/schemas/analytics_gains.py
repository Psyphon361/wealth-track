from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel

from app.schemas.assets import Number

Amount = Annotated[Decimal, Number]

Term = Literal["short", "long", "flat"]
Flag = Literal[
    "grandfathering", "no_purchase_date", "guessed_class", "old_rules", "multi_asset", "estimated"
]
Source = Literal["sale", "maturity", "planned_sale"]


class GainsFy(BaseModel):
    start_year: int
    label: str
    is_current: bool


class GainsSummary(BaseModel):
    short_term_net: Amount
    long_term_net: Amount
    losses_set_off: Amount
    unused_losses: Amount
    exemption_used: Amount
    fixed_rate_tax: Amount
    slab_gains: Amount
    sales_count: int


class GainsBucket(BaseModel):
    key: str
    label: str
    term: Term
    rate: Amount | None = None
    gains: Amount
    losses: Amount
    net: Amount
    set_off: Amount
    exemption: Amount
    taxable: Amount
    tax: Amount | None = None


class GainsLot(BaseModel):
    bought_on: date | None = None
    quantity: Amount | None = None
    cost: Amount
    proceeds: Amount
    gain: Amount
    days_held: int | None = None
    term: Term | None = None
    bucket: str | None = None


class GainsSale(BaseModel):
    exit_id: int | None = None
    source: Source
    estimated: bool
    asset_type: Literal["stock", "bond", "mf", "gold", "other"]
    holding_id: int
    name: str
    sold_on: date
    proceeds: Amount
    cost: Amount
    gain: Amount
    flags: list[Flag]
    lots: list[GainsLot]


class GainsTaxFreeItem(BaseModel):
    exit_id: int | None = None
    holding_id: int
    name: str
    settled_on: date
    amount: Amount
    cost: Amount
    gain: Amount
    estimated: bool


class GainsTaxFree(BaseModel):
    total: Amount
    items: list[GainsTaxFreeItem]


class GainsExcluded(BaseModel):
    bonds_no_face: int
    no_purchase_date: int
    old_rules: int


class GainsBondInterest(BaseModel):
    interest_to_date: Amount
    interest_projected: Amount
    tds_estimate: Amount
    holdings_count: int


class AnalyticsGains(BaseModel):
    fy: str
    fy_start: date
    fy_end: date
    as_of: date
    is_current: bool
    available_fys: list[GainsFy]
    summary: GainsSummary
    buckets: list[GainsBucket]
    sales: list[GainsSale]
    expected: list[GainsSale]
    expected_gain: Amount
    tax_free: GainsTaxFree
    bond_interest: GainsBondInterest | None = None
    excluded: GainsExcluded

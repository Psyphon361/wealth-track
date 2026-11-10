from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel

from app.schemas.analytics_gains import GainsFy, Term
from app.schemas.assets import Number

Amount = Annotated[Decimal, Number]

UnrealisedFlag = Literal[
    "grandfathering",
    "no_purchase_date",
    "guessed_class",
    "old_rules",
    "multi_asset",
    "estimated",
    "single_lot_average",  # a stock is one average-price lot, not its real purchase lots
    "single_lot_fallback",  # a fund with transactions whose lot units do not add up: one lot
]
HoldingType = Literal["stock", "bond", "mf", "gold", "other"]


class UnrealisedLot(BaseModel):
    bought_on: date | None = None
    quantity: Amount | None = None
    cost: Amount
    value: Amount
    gain: Amount
    days_held: int | None = None
    term: Term | None = None
    long_term_on: date | None = None
    days_to_long_term: int | None = None
    bucket: str | None = None
    bucket_after: str | None = None


class UnrealisedHolding(BaseModel):
    asset_type: HoldingType
    holding_id: int
    name: str
    cost: Amount
    value: Amount
    gain: Amount
    flags: list[UnrealisedFlag]
    lots: list[UnrealisedLot]


class UnrealisedSummary(BaseModel):
    total_gain: Amount
    short_term_net: Amount
    long_term_net: Amount
    uncounted_lots: int


class UnrealisedBucket(BaseModel):
    key: str
    label: str
    term: Term
    rate: Amount | None = None
    gains: Amount
    losses: Amount
    net: Amount


class TurningLot(BaseModel):
    asset_type: HoldingType
    holding_id: int
    name: str
    bought_on: date | None = None
    quantity: Amount | None = None
    gain: Amount
    bucket: str | None = None
    bucket_after: str | None = None
    long_term_on: date
    days_to_long_term: int


class LossLot(BaseModel):
    asset_type: HoldingType
    holding_id: int
    name: str
    bought_on: date | None = None
    quantity: Amount | None = None
    gain: Amount
    bucket: str | None = None
    term: Term | None = None


class UnrealisedHarvest(BaseModel):
    exemption_limit: Amount
    exemption_used: Amount
    exemption_room: Amount
    unrealised_equity_lt_gain: Amount
    turning_long_term: list[TurningLot]
    loss_lots: list[LossLot]


class UnrealisedExcluded(BaseModel):
    at_cost: int  # stock, fund or gold without a price (valued at cost)
    no_invested_amount: int  # Other holdings with no invested amount (no gain to report)
    bonds_no_face: int
    no_purchase_date: int


class AnalyticsUnrealised(BaseModel):
    fy: str
    fy_start: date
    fy_end: date
    as_of: date
    is_current: bool
    available_fys: list[GainsFy]
    summary: UnrealisedSummary
    buckets: list[UnrealisedBucket]
    harvest: UnrealisedHarvest
    holdings: list[UnrealisedHolding]
    excluded: UnrealisedExcluded

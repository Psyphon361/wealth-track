from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.summary import Amount, AssetType

# Shapes returned by app/services/analytics.py. Money and percents are Amount (JSON numbers);
# dates are YYYY-MM-DD.


# --- Allocation --------------------------------------------------------------------------------


class AllocationHolding(BaseModel):
    id: int
    name: str
    value: Amount
    percent: Amount


class AllocationType(BaseModel):
    type: AssetType
    label: str
    value: Amount
    percent: Amount
    holdings: list[AllocationHolding]


class AllocationClass(BaseModel):
    # The JSON key is "class", a Python keyword.
    model_config = ConfigDict(populate_by_name=True)

    class_: str = Field(alias="class")
    label: str
    value: Amount
    percent: Amount
    types: list[AllocationType]


class AllocationView(BaseModel):
    total: Amount
    classes: list[AllocationClass]


class AllocationSection(BaseModel):
    including_retirement: AllocationView
    excluding_retirement: AllocationView
    retirement_value: Amount
    retirement_percent: Amount


# --- Concentration -----------------------------------------------------------------------------


class TopHolding(BaseModel):
    type: AssetType
    id: int
    name: str
    value: Amount
    percent: Amount


class RollupBar(BaseModel):
    key: str
    label: str
    value: Amount
    percent: Amount
    passive: bool


class Rollup(BaseModel):
    key: str
    label: str
    total: Amount
    bars: list[RollupBar]


class ConcentrationFlag(BaseModel):
    kind: Literal["single_stock", "amc"]
    key: str
    label: str
    value: Amount
    percent: Amount
    threshold: Amount


class ConcentrationOthers(BaseModel):
    count: int
    value: Amount
    percent: Amount


class ConcentrationSection(BaseModel):
    total: Amount
    top_holdings: list[TopHolding]
    others: ConcentrationOthers
    rollups: list[Rollup]
    flags: list[ConcentrationFlag]


# --- Liquidity ---------------------------------------------------------------------------------


class LiquidityBucket(BaseModel):
    key: str
    label: str
    amount: Amount
    percent: Amount


class LiquiditySection(BaseModel):
    total: Amount
    buckets: list[LiquidityBucket]


# --- Coming up ---------------------------------------------------------------------------------


class MaturityRow(BaseModel):
    type: AssetType
    id: int
    name: str
    maturity_date: date
    amount: Amount
    rate: Amount
    days_left: int
    approximate: bool


class MaturityWindow(BaseModel):
    until: date
    total: Amount
    rows: list[MaturityRow]


class MaturedHolding(BaseModel):
    type: AssetType
    id: int
    name: str
    maturity_date: date | None = None
    # What it paid at maturity (the amount received once settled); null when unknown.
    amount: Amount | None = None
    # True once where the money went has been recorded.
    settled: bool = False


class AlreadyMatured(BaseModel):
    count: int
    rows: list[MaturedHolding]


class ComingUpSection(BaseModel):
    next_30_days: MaturityWindow
    next_90_days: MaturityWindow
    next_180_days: MaturityWindow
    next_12_months: MaturityWindow
    already_matured: AlreadyMatured


# --- Bank safety -------------------------------------------------------------------------------


class BankHolding(BaseModel):
    type: AssetType
    id: int
    name: str
    label: str | None = None
    rate: Amount | None = None
    maturity_date: date | None = None
    payout: bool = False
    amount: Amount


class BankRow(BaseModel):
    key: str
    name: str
    issuer_id: int | None = None
    category: str | None = None
    status: Literal["insured", "not_insured", "sovereign", "unknown"]
    badges: list[str]
    total: Amount
    insured: Amount | None = None
    excess: Amount | None = None
    holdings: list[BankHolding]


class BankSafetySection(BaseModel):
    limit: Amount
    total_deposits: Amount
    insured: Amount
    uninsured_excess: Amount
    unknown_amount: Amount
    sovereign_amount: Amount
    banks: list[BankRow]


# --- Data health -------------------------------------------------------------------------------


class HealthItem(BaseModel):
    type: AssetType
    id: int
    name: str


class StaleItem(HealthItem):
    as_of: date


class MaturedItem(HealthItem):
    maturity_date: date | None = None


class AtCost(BaseModel):
    count: int
    items: list[HealthItem]


class StaleBalances(BaseModel):
    count: int
    items: list[StaleItem]


class MaturedOpen(BaseModel):
    count: int
    items: list[MaturedItem]


class LatestDates(BaseModel):
    stock_price: date | None = None
    mf_nav: date | None = None
    nps_nav: date | None = None
    gold_rate: date | None = None


class DataHealthSection(BaseModel):
    at_cost: AtCost
    stale_balances: StaleBalances
    matured_open: MaturedOpen
    latest: LatestDates


# --- Response ----------------------------------------------------------------------------------


class AnalyticsOverview(BaseModel):
    as_of: date
    allocation: AllocationSection
    concentration: ConcentrationSection
    liquidity: LiquiditySection
    coming_up: ComingUpSection
    bank_safety: BankSafetySection
    data_health: DataHealthSection

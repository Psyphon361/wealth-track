from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    model_validator,
)

# Decimals are emitted as JSON numbers (frontend types them as `number`).
Number = PlainSerializer(float, return_type=float, when_used="json")
Money = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2), Number]
Rate = Annotated[Decimal, Field(gt=0, max_digits=6, decimal_places=3), Number]
Units = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3), Number]
Quantity = Annotated[int, Field(gt=0)]
Tenure = Annotated[int, Field(ge=0)]


def _blank_to_none(value: object) -> object:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


Required = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Optional = Annotated[
    Annotated[str, StringConstraints(max_length=200)] | None,
    BeforeValidator(_blank_to_none),
    Field(default=None),
]
OptionalShort = Annotated[
    Annotated[str, StringConstraints(max_length=50)] | None,
    BeforeValidator(_blank_to_none),
    Field(default=None),
]
Notes = Annotated[str | None, BeforeValidator(_blank_to_none), Field(default=None)]

Compounding = Literal["monthly", "quarterly", "half_yearly", "yearly", "simple"]


class _Create(BaseModel):
    notes: Notes


class _Read(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class _Tenure(BaseModel):
    tenure_years: Tenure = 0
    tenure_months: Tenure = 0
    tenure_days: Tenure = 0

    @model_validator(mode="after")
    def _total_positive(self):
        if self.tenure_years + self.tenure_months + self.tenure_days <= 0:
            raise ValueError("total tenure must be greater than 0")
        return self


class FixedDepositCreate(_Tenure, _Create):
    bank: Required
    label: Optional
    principal: Money
    rate: Rate
    start_date: date
    compounding: Compounding = "quarterly"
    payout_type: Literal["cumulative", "payout"]


class FixedDepositRead(FixedDepositCreate, _Read):
    pass


class RecurringDepositCreate(_Tenure, _Create):
    bank: Required
    label: Optional
    monthly_instalment: Money
    rate: Rate
    start_date: date
    compounding: Compounding = "quarterly"


class RecurringDepositRead(RecurringDepositCreate, _Read):
    pass


class StockCreate(_Create):
    name: Required
    symbol: OptionalShort
    exchange: Literal["NSE", "BSE"] = "NSE"
    broker: Optional
    quantity: Quantity
    avg_buy_price: Money
    buy_date: date


class StockRead(StockCreate, _Read):
    pass


class BondCreate(_Create):
    name: Required
    isin: Annotated[
        Annotated[str, StringConstraints(max_length=20)] | None,
        BeforeValidator(_blank_to_none),
        Field(default=None),
    ]
    issuer: Required
    bond_type: Literal["government", "corporate", "tax_free", "sgb", "other"]
    platform: Optional
    quantity: Quantity
    face_value: Money
    purchase_price: Money
    purchase_date: date
    ytm: Rate
    maturity_date: date

    @model_validator(mode="after")
    def _maturity_after_purchase(self):
        if self.maturity_date <= self.purchase_date:
            raise ValueError("maturity_date must be after purchase_date")
        return self


class BondRead(BondCreate, _Read):
    # Nullable: rows created before face_value existed have no value.
    face_value: Annotated[Decimal, Number] | None = None


class MutualFundCreate(_Create):
    scheme_name: Required
    platform: Optional
    category: Literal["equity", "debt", "hybrid", "index", "elss", "liquid", "other"]
    units: Units
    avg_nav: Money
    purchase_date: date


class MutualFundRead(MutualFundCreate, _Read):
    pass

import math
import re
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal, NoReturn

from dateutil.relativedelta import relativedelta
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    ValidationError,
    model_validator,
)
from pydantic_core import PydanticCustomError

# Decimals are emitted as JSON numbers (frontend types them as `number`).
Number = PlainSerializer(float, return_type=float, when_used="json")

MAX_MONEY = Decimal("1000000000")
MAX_QUANTITY = 10_000_000
MIN_DATE = date(1990, 1, 1)


def _error(message: str) -> PydanticCustomError:
    return PydanticCustomError("value_error", message)


def _positive(value):
    if value <= 0:
        raise _error("Must be greater than 0")
    return value


def _max_money(value: Decimal) -> Decimal:
    if value > MAX_MONEY:
        raise _error("Must be at most ₹100 crore")
    return value


def _max_quantity(value):
    if value > MAX_QUANTITY:
        raise _error("Must be at most 1 crore")
    return value


def _decimals(places: int) -> Callable[[Decimal], Decimal]:
    def check(value: Decimal) -> Decimal:
        if value.is_finite() and value.normalize().as_tuple().exponent < -places:
            raise _error(f"Up to {places} decimal places allowed")
        return value

    return check


def _whole_number(value: object) -> object:
    fractional = False
    if isinstance(value, float):
        fractional = math.isfinite(value) and not value.is_integer()
    elif isinstance(value, (str, Decimal)):
        try:
            number = Decimal(value)
            fractional = number.is_finite() and number != number.to_integral_value()
        except ArithmeticError:
            pass
    if fractional:
        raise _error("Must be a whole number")
    return value


def _tenure_part(label: str, maximum: int) -> Callable[[int], int]:
    def check(value: int) -> int:
        if not 0 <= value <= maximum:
            raise _error(f"{label} must be between 0 and {maximum}")
        return value

    return check


def _max_length(maximum: int) -> Callable[[str | None], str | None]:
    def check(value: str | None) -> str | None:
        if value is not None and len(value) > maximum:
            raise _error(f"Must be at most {maximum} characters")
        return value

    return check


def _required(value: str) -> str:
    if not value:
        raise _error("Required")
    return value


def _min_date(value: date) -> date:
    if value < MIN_DATE:
        raise _error("Date must be on or after 1 Jan 1990")
    return value


def _not_far_future(value: date) -> date:
    # Evaluated at validation time, not import time.
    if value > date.today() + timedelta(days=30):
        raise _error("Date can be at most 30 days in the future")
    return value


def _percent(maximum: int, message: str) -> Callable[[Decimal], Decimal]:
    def check(value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0 or value > maximum:
            raise _error(message)
        return _decimals(2)(value)

    return check


# Lenient types (Read models): accept whatever is already stored.
Dec = Annotated[Decimal, Number]

# Strict types (Create models).
Money = Annotated[
    Decimal,
    AfterValidator(_positive),
    AfterValidator(_decimals(2)),
    AfterValidator(_max_money),
    Number,
]
Nav = Annotated[
    Decimal,
    AfterValidator(_positive),
    AfterValidator(_decimals(4)),
    AfterValidator(_max_money),
    Number,
]
Units = Annotated[
    Decimal,
    AfterValidator(_positive),
    AfterValidator(_decimals(3)),
    AfterValidator(_max_quantity),
    Number,
]
Quantity = Annotated[
    int,
    BeforeValidator(_whole_number),
    AfterValidator(_positive),
    AfterValidator(_max_quantity),
]
FdRate = Annotated[
    Decimal, AfterValidator(_percent(15, "Interest rate must be between 0 and 15%")), Number
]
YtmRate = Annotated[Decimal, AfterValidator(_percent(30, "YTM must be between 0 and 30%")), Number]
PastDate = Annotated[date, AfterValidator(_min_date)]
TradeDate = Annotated[date, AfterValidator(_min_date), AfterValidator(_not_far_future)]


def _blank_to_none(value: object) -> object:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _normalise_code(value: object) -> object:
    value = _blank_to_none(value)
    return value.upper() if isinstance(value, str) else value


def _pattern_check(pattern: str, message: str) -> Callable[[str | None], str | None]:
    compiled = re.compile(pattern)

    def check(value: str | None) -> str | None:
        if value is not None and not compiled.fullmatch(value):
            raise _error(message)
        return value

    return check


Required = Annotated[
    str,
    StringConstraints(strip_whitespace=True),
    AfterValidator(_required),
    AfterValidator(_max_length(200)),
]
Optional = Annotated[
    str | None,
    BeforeValidator(_blank_to_none),
    AfterValidator(_max_length(200)),
    Field(default=None),
]
Notes = Annotated[
    str | None,
    BeforeValidator(_blank_to_none),
    AfterValidator(_max_length(1000)),
    Field(default=None),
]
Symbol = Annotated[
    str | None,
    BeforeValidator(_normalise_code),
    AfterValidator(
        _pattern_check(
            r"[A-Z0-9&-]{1,20}", "Symbol: letters, digits, & or -, up to 20 characters"
        )
    ),
    Field(default=None),
]
Isin = Annotated[
    str | None,
    BeforeValidator(_normalise_code),
    AfterValidator(
        _pattern_check(
            r"[A-Z]{2}[A-Z0-9]{9}[0-9]", "ISIN must be 12 characters, e.g. INE002A01018"
        )
    ),
    Field(default=None),
]

Compounding = Literal["monthly", "quarterly", "half_yearly", "yearly", "simple"]


class _Create(BaseModel):
    """Mixin listed first in Create models so its strict `notes` wins."""

    notes: Notes


class _Read(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    notes: str | None = None


def _field_error(model: BaseModel, field: str, message: str) -> NoReturn:
    """Raise a validation error whose `loc` points at `field`."""
    raise ValidationError.from_exception_data(
        type(model).__name__,
        [
            {
                "type": _error(message),
                "loc": (field,),
                "input": getattr(model, field, None),
            }
        ],
    )


def _maturity(start: date, years: int, months: int, days: int) -> date:
    return start + relativedelta(years=years, months=months) + timedelta(days=days)


class _Tenure(BaseModel):
    tenure_years: Annotated[int, AfterValidator(_tenure_part("Years", 10))] = 0
    tenure_months: Annotated[int, AfterValidator(_tenure_part("Months", 11))] = 0
    tenure_days: Annotated[int, AfterValidator(_tenure_part("Days", 30))] = 0

    def _check_tenure(self, start: date, low: date, high: date, message: str) -> None:
        if self.tenure_years + self.tenure_months + self.tenure_days <= 0:
            _field_error(self, "tenure_years", "Tenure must be greater than zero")
        maturity = _maturity(start, self.tenure_years, self.tenure_months, self.tenure_days)
        if not low <= maturity <= high:
            _field_error(self, "tenure_years", message)


# --- Fixed deposits ---------------------------------------------------------


class FixedDepositBase(BaseModel):
    bank: Required
    issuer_id: int | None = None
    label: Optional
    principal: Dec
    rate: Dec
    start_date: date
    compounding: Compounding = "quarterly"
    payout_type: Literal["cumulative", "payout"]
    tenure_years: int = 0
    tenure_months: int = 0
    tenure_days: int = 0


class FixedDepositCreate(_Create, _Tenure, FixedDepositBase):
    principal: Money
    rate: FdRate
    start_date: TradeDate

    @model_validator(mode="after")
    def _tenure_range(self):
        if self.payout_type == "payout" and self.compounding == "simple":
            _field_error(self, "compounding", "Choose a payout frequency")
        start = self.start_date
        self._check_tenure(
            start,
            start + timedelta(days=7),
            start + relativedelta(years=10),
            "FD tenure must be between 7 days and 10 years",
        )
        return self


class FixedDepositRead(FixedDepositBase, _Read):
    pass


# --- Recurring deposits -----------------------------------------------------


class RecurringDepositBase(BaseModel):
    bank: Required
    issuer_id: int | None = None
    label: Optional
    monthly_instalment: Dec
    rate: Dec
    start_date: date
    compounding: Compounding = "quarterly"
    tenure_years: int = 0
    tenure_months: int = 0
    tenure_days: int = 0


class RecurringDepositCreate(_Create, _Tenure, RecurringDepositBase):
    monthly_instalment: Money
    rate: FdRate
    start_date: TradeDate

    @model_validator(mode="after")
    def _tenure_range(self):
        start = self.start_date
        self._check_tenure(
            start,
            start + relativedelta(months=6),
            start + relativedelta(years=10),
            "RD tenure must be between 6 months and 10 years",
        )
        return self


class RecurringDepositRead(RecurringDepositBase, _Read):
    pass


# --- Stocks -----------------------------------------------------------------


class StockBase(BaseModel):
    name: Required
    symbol: Annotated[str | None, Field(default=None)]
    master_id: int | None = None
    exchange: Literal["NSE", "BSE"] = "NSE"
    broker: Optional
    quantity: int
    avg_buy_price: Dec
    buy_date: date


class StockCreate(_Create, StockBase):
    symbol: Symbol
    quantity: Quantity
    avg_buy_price: Money
    buy_date: TradeDate


class StockRead(StockBase, _Read):
    pass


# --- Bonds ------------------------------------------------------------------


class BondBase(BaseModel):
    name: Required
    isin: Annotated[str | None, Field(default=None)]
    master_id: int | None = None
    issuer: Required
    bond_type: Literal["government", "corporate", "tax_free", "sgb", "other"]
    platform: Optional
    quantity: int
    # Nullable: rows created before face_value existed have no value.
    face_value: Dec | None = None
    purchase_price: Dec
    invested_amount: Dec
    purchase_date: date
    ytm: Dec
    maturity_date: date


class BondCreate(_Create, BondBase):
    isin: Isin
    quantity: Quantity
    face_value: Money | None = None
    purchase_price: Money
    invested_amount: Money
    purchase_date: TradeDate
    ytm: YtmRate
    maturity_date: PastDate

    @model_validator(mode="after")
    def _cross_field(self):
        if self.maturity_date <= self.purchase_date:
            _field_error(self, "maturity_date", "Maturity date must be after the purchase date")
        if self.maturity_date > self.purchase_date + relativedelta(years=50):
            _field_error(self, "maturity_date", "Maturity must be within 50 years of purchase")
        tolerance = self.quantity * Decimal("0.005") + Decimal("0.01")
        if abs(self.quantity * self.purchase_price - self.invested_amount) > tolerance:
            _field_error(
                self,
                "invested_amount",
                "Total invested must equal quantity × purchase price",
            )
        return self


class BondRead(BondBase, _Read):
    pass


# --- Mutual funds -----------------------------------------------------------


class MutualFundBase(BaseModel):
    scheme_name: Required
    scheme_code: int | None = None
    platform: Optional
    category: Literal["equity", "debt", "hybrid", "index", "elss", "liquid", "other"]
    units: Dec
    avg_nav: Dec
    purchase_date: date


class MutualFundCreate(_Create, MutualFundBase):
    units: Units
    avg_nav: Nav
    purchase_date: TradeDate


class MutualFundRead(MutualFundBase, _Read):
    pass

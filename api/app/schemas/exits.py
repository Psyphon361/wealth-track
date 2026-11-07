"""Request and response models for closing holdings: sell, settle a maturity, undo.

The validation messages are shared verbatim with the web forms. Messages that already exist in
schemas/assets.py are reused: "Required", "Must be greater than 0", "Must be a whole number",
"Up to 3 decimal places allowed" (quantity), "Up to 4 decimal places allowed" (price),
"Up to 2 decimal places allowed" (charges, amounts), "Must be at most ₹100 crore",
"Must be at most 1 crore" (quantity), "Must be at most 200 characters" (new account name) and
"Date must be on or after 1 Jan 1990".
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, model_validator

from app.schemas.assets import (
    Money,
    Number,
    _blank_to_none,
    _decimals,
    _error,
    _field_error,
    _max_money,
    _max_quantity,
    _min_date,
    _one_of,
    _positive,
)
from app.schemas.messages import Outcome

Day = date  # alias for fields that are themselves named "date"

EXIT_DATE_FUTURE_ERROR = "Date can't be in the future"
SELL_DATE_BEFORE_PURCHASE_ERROR = "Date can't be before the purchase date"
SETTLE_DATE_BEFORE_MATURITY_ERROR = "Date can't be before the maturity date"
SELL_QUANTITY_TOO_MANY_ERROR = "Can't sell more than you hold"
CHARGES_NEGATIVE_ERROR = "Can't be negative"
CHARGES_TOO_HIGH_ERROR = "Charges must be less than the sale value"
DESTINATION_ERROR = "Choose where the money went"
CASH_ACCOUNT_ERROR = "Choose one of your accounts"
CASH_NAME_REQUIRED_ERROR = "Required"
CASH_NAME_LENGTH_ERROR = "Must be at most 200 characters"

CASH_NAME_MAX = 200
SELL_DESTINATIONS = ("cash_existing", "cash_new", "none")
SETTLE_DESTINATIONS = ("cash_existing", "cash_new", "none")


def _not_negative(value: Decimal) -> Decimal:
    if value < 0:
        raise _error(CHARGES_NEGATIVE_ERROR)
    return value


SaleQuantity = Annotated[
    Decimal,
    AfterValidator(_positive),
    AfterValidator(_decimals(3)),
    AfterValidator(_max_quantity),
    Number,
]
SalePrice = Annotated[
    Decimal,
    AfterValidator(_positive),
    AfterValidator(_decimals(4)),
    AfterValidator(_max_money),
    Number,
]
Charges = Annotated[
    Decimal,
    AfterValidator(_not_negative),
    AfterValidator(_decimals(2)),
    AfterValidator(_max_money),
    Number,
]
ExitDate = Annotated[date, AfterValidator(_min_date)]


class _Destination(BaseModel):
    kind: str
    cash_id: int | None = None
    cash_name: Annotated[str | None, BeforeValidator(_blank_to_none)] = None

    def _check_cash(self) -> None:
        if self.kind == "cash_existing" and self.cash_id is None:
            _field_error(self, "cash_id", CASH_ACCOUNT_ERROR)
        if self.kind == "cash_new":
            if self.cash_name is None:
                _field_error(self, "cash_name", CASH_NAME_REQUIRED_ERROR)
            if len(self.cash_name) > CASH_NAME_MAX:
                _field_error(self, "cash_name", CASH_NAME_LENGTH_ERROR)


class SellDestination(_Destination):
    kind: Annotated[
        Literal["cash_existing", "cash_new", "none"],
        BeforeValidator(_one_of(SELL_DESTINATIONS, DESTINATION_ERROR)),
    ]

    @model_validator(mode="after")
    def _cash(self):
        self._check_cash()
        return self


class SettleDestination(_Destination):
    kind: Annotated[
        Literal["cash_existing", "cash_new", "none"],
        BeforeValidator(_one_of(SETTLE_DESTINATIONS, DESTINATION_ERROR)),
    ]

    @model_validator(mode="after")
    def _cash(self):
        self._check_cash()
        return self


class SellBody(BaseModel):
    date: ExitDate
    # Shares, bond units, fund units or grams. Omit for Other (always sold whole).
    quantity: SaleQuantity | None = None
    # Price per unit; for Other send `amount` (the sale value before charges) instead.
    price: SalePrice | None = None
    amount: Money | None = None
    charges: Charges = Decimal("0")
    destination: SellDestination


class SettleBody(BaseModel):
    # Both default: the maturity date, and the amount the deposit or bond pays at maturity.
    date: ExitDate | None = None
    amount: Money | None = None
    destination: SettleDestination


class ExitRead(BaseModel):
    id: int
    asset_type: str
    holding_id: int
    kind: Literal["maturity", "sale"]
    date: Day
    quantity: Annotated[Decimal, Number] | None
    amount: Annotated[Decimal, Number]
    cost: Annotated[Decimal, Number]
    charges: Annotated[Decimal, Number]
    destination: str
    cash_holding_id: int | None
    cash_added: Annotated[Decimal, Number] | None
    new_holding_id: int | None
    new_asset_type: str | None
    created_at: datetime
    # amount - cost: the realised gain (negative for a loss).
    realised_gain: Annotated[Decimal, Number]
    # Money of this exit put into holdings that still exist ("Paid from" this exit).
    reinvested: Annotated[Decimal, Number]
    # cash_added - reinvested, never below 0; null when the money went into no account.
    left_in_account: Annotated[Decimal, Number] | None


class ExitResult(ExitRead, Outcome):
    """An exit plus the outcome text of recording it."""

    # True when the whole holding is now closed (sold out or settled).
    closed: bool
    # Quantity left after a partial sale; null when closed or for Other.
    remaining: Annotated[Decimal, Number] | None = None
    # Name of the cash account that got the money, when one did.
    cash_name: str | None = None
    # Number of SIPs cancelled by selling every unit of a fund.
    sips_cancelled: int = 0


class ExitSummary(BaseModel):
    """The `exit` object on holding items (grid, details, portfolio): the latest exit."""

    id: int
    kind: str
    date: Day
    quantity: Annotated[Decimal, Number] | None = None
    amount: Annotated[Decimal, Number]
    cost: Annotated[Decimal, Number]
    charges: Annotated[Decimal, Number]
    destination: str
    cash_holding_id: int | None
    new_holding_id: int | None
    new_asset_type: str | None = None
    reinvested: Annotated[Decimal, Number]
    left_in_account: Annotated[Decimal, Number] | None


class StockClose(BaseModel):
    """A stock's close on or just before a date (prefills the sell price)."""

    price: Annotated[Decimal, Number]
    price_date: date
    # "history" (stored daily close) or "latest" (the newest stored close).
    source: Literal["history", "latest"]


class UnsettledItem(BaseModel):
    type: Literal["fd", "rd", "bond"]
    id: int
    name: str
    maturity_date: date
    amount: Annotated[Decimal, Number]


class Unsettled(BaseModel):
    """Matured deposits and bonds whose payout has not been recorded yet."""

    count: int = 0
    amount: Annotated[Decimal, Number] = Decimal("0")
    items: list[UnsettledItem] = []

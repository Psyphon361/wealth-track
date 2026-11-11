"""Request and response models for Buy more (adding units to a mutual fund) and undoing a buy.

The validation messages are shared verbatim with the web form. Messages that already exist are
reused from schemas/assets.py and schemas/exits.py: "Required", "Must be greater than 0",
"Up to 2 decimal places allowed" (amount), "Up to 4 decimal places allowed" (NAV),
"Up to 3 decimal places allowed" (units), "Must be at most ₹100 crore", "Must be at most 1 crore",
"Date must be on or after 1 Jan 1990", "Date can't be in the future" and
"Date can't be before the purchase date".
"""

from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel

from app.schemas.assets import Money, Number, _decimals, _max_money, _max_quantity, _min_date, _positive
from app.schemas.messages import Outcome

Day = date  # alias for fields that are themselves named "date"

BUY_DATE_BEFORE_LAST_SALE_ERROR = "Date can't be before the last sale"

BUY_AMOUNT_TOO_SMALL_ERROR = "Amount is too small for this many units"
BUY_DONE_MESSAGE ="More units added"
BUY_DUPLICATE_MESSAGE = "Looks like a buy you already made"
BUY_UNDONE_MESSAGE = "Buy undone"
BUY_UNDO_SALE_FIRST_MESSAGE = "Undo the later sale first"
BUY_UNDO_SALE_FIRST_DESCRIPTION = "A sale dated on or after this buy's date may have used these units."
BUY_UNDO_REFUSED_MESSAGE = "Can't undo this buy"
BUY_UNDO_REFUSED_DESCRIPTION = (
    "Removing it would leave the fund with no units or too little invested."
)
BUY_NOT_MF_MESSAGE = "Can't add to this holding"

BuyDate = Annotated[date, AfterValidator(_min_date)]
BuyNav = Annotated[
    Decimal,
    AfterValidator(_positive),
    AfterValidator(_decimals(4)),
    AfterValidator(_max_money),
    Number,
]
BuyUnits = Annotated[
    Decimal,
    AfterValidator(_positive),
    AfterValidator(_decimals(3)),
    AfterValidator(_max_quantity),
    Number,
]


class BuyBody(BaseModel):
    date: BuyDate
    # Money paid, 2 dp.
    amount: Money
    # NAV per unit, 4 dp.
    nav: BuyNav
    # Units from the statement; default is amount / nav rounded to 3 dp.
    units: BuyUnits | None = None


class BuyResult(Outcome):
    transaction_id: int
    units_added: Annotated[Decimal, Number]
    # The fund's totals after the buy.
    units: Annotated[Decimal, Number]
    invested_amount: Annotated[Decimal, Number]
    avg_nav: Annotated[Decimal, Number]

"""SIP request and response models. The validation messages are shared verbatim with the web form."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict

from app.schemas.assets import (
    Number,
    Required,
    _decimals,
    _error,
    _max_money,
    _min_date,
    _whole_number,
)
from app.schemas.messages import Outcome

Day = date  # alias for fields that are themselves named "date"

MIN_SIP_AMOUNT = Decimal("100")
MIN_DAY = 1
MAX_DAY = 28

SIP_AMOUNT_MIN_ERROR = "Must be at least ₹100"
SIP_DAY_ERROR = "Day must be between 1 and 28"
SIP_START_DATE_FUTURE_ERROR = "Date can be at most 1 year in the future"
SIP_END_BEFORE_START_ERROR = "End date must be on or after the start date"
SIP_INACTIVE_SCHEME_ERROR = "This scheme is no longer active"
SIP_SKIP_NOT_UPCOMING_ERROR = "Pick an upcoming instalment date"
SIP_NO_INSTALMENT_ERROR = "There is no upcoming instalment to skip"
SIP_HOLDING_MISMATCH_ERROR = "This holding is a different fund"
SIP_HOLDING_SOLD_ERROR = "This holding has been sold"
# Amount above the limit and dates before 1990 reuse the shared messages in schemas/assets.py:
# "Must be at most ₹100 crore" and "Date must be on or after 1 Jan 1990".


def _min_amount(value: Decimal) -> Decimal:
    if not value.is_finite() or value < MIN_SIP_AMOUNT:
        raise _error(SIP_AMOUNT_MIN_ERROR)
    return value


def _day(value: int) -> int:
    if not MIN_DAY <= value <= MAX_DAY:
        raise _error(SIP_DAY_ERROR)
    return value


def _not_over_a_year_ahead(value: date) -> date:
    # Evaluated at validation time, not import time.
    if value > date.today() + timedelta(days=366):
        raise _error(SIP_START_DATE_FUTURE_ERROR)
    return value


SipAmount = Annotated[
    Decimal,
    AfterValidator(_min_amount),
    AfterValidator(_decimals(2)),
    AfterValidator(_max_money),
    Number,
]
SipDay = Annotated[int, BeforeValidator(_whole_number), AfterValidator(_day)]
SipStartDate = Annotated[date, AfterValidator(_min_date), AfterValidator(_not_over_a_year_ahead)]
SipEndDate = Annotated[date, AfterValidator(_min_date)]


class SipCreate(BaseModel):
    scheme_code: int
    platform: Required
    amount: SipAmount
    day_of_month: SipDay
    start_date: SipStartDate
    include_past: bool = False
    mutual_fund_id: int | None = None


class SipUpdate(BaseModel):
    amount: SipAmount
    day_of_month: SipDay
    end_date: SipEndDate | None = None


class SipSkipBody(BaseModel):
    due_date: date | None = None


class SipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    mutual_fund_id: int | None
    scheme_code: int
    fund_name: str
    platform: str
    amount: Annotated[Decimal, Number]
    day_of_month: int
    start_date: date
    end_date: date | None
    status: str
    next_date: date | None
    skipped_dates: list[date]
    instalments_added: int
    invested_via_sip: Annotated[Decimal, Number]


class SipResult(SipRead, Outcome):
    """A SIP plus the outcome text of the operation."""


class SipTransaction(BaseModel):
    id: int
    date: Day
    kind: str
    amount: Annotated[Decimal, Number]
    units: Annotated[Decimal, Number]
    nav: Annotated[Decimal, Number] | None
    sip: bool


class SipTransactionsResponse(BaseModel):
    items: list[SipTransaction]
    total: int
    page: int
    page_size: int
    page_count: int

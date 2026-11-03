from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel

from app.schemas.assets import Number

Amount = Annotated[Decimal, Number]


class GrowthPeriod(BaseModel):
    key: str
    label: str
    start_date: date
    end_date: date
    start_value: Amount
    end_value: Amount
    new_money: Amount
    growth: Amount
    change: Amount
    growth_pct: Amount | None


class GrowthMonth(BaseModel):
    month: str
    start_value: Amount
    end_value: Amount
    new_money: Amount
    growth: Amount
    change: Amount


class AnalyticsGrowth(BaseModel):
    as_of: date
    stocks_at_cost_before: date | None
    periods: list[GrowthPeriod]
    months: list[GrowthMonth]

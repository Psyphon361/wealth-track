from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel

from app.schemas.assets import Number

Amount = Annotated[Decimal, Number]


class NetWorthPoint(BaseModel):
    date: date
    invested: Amount
    current: Amount


class NetWorthHistoryResponse(BaseModel):
    range: Literal["1m", "6m", "1y", "all"]
    points: list[NetWorthPoint]
    stocks_at_cost_before: date | None

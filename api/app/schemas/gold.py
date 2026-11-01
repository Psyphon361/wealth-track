from datetime import date

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, PlainSerializer


class GoldImportResult(BaseModel):
    rate_date: date
    session: str
    rows_upserted: int


class GoldRateOnDate(BaseModel):
    metal: str
    purity: str
    requested_date: date
    rate_date: date
    rate_per_gram: Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]

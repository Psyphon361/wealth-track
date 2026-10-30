from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.summary import Amount


class HoldingsSummary(BaseModel):
    count: int
    matured_count: int
    invested: Amount
    current_value: Amount
    gain: Amount
    gain_pct: Amount


class FacetValue(BaseModel):
    value: str
    count: int


class HoldingsResponse(BaseModel):
    # Each item: the asset's Read-schema fields plus computed fields (as in /api/portfolio).
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
    page_count: int
    summary: HoldingsSummary
    facets: dict[str, list[FacetValue]]
    prices_as_of: datetime | None = None  # stocks only: latest price_time over held stocks

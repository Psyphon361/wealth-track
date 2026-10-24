from typing import Any, Literal

from pydantic import BaseModel

from app.schemas.summary import Amount

AssetType = Literal["fd", "rd", "stock", "bond", "mf"]
HoldingStatus = Literal["active", "matured"]


class HoldingRow(BaseModel):
    id: int
    type: AssetType
    name: str
    detail: str | None = None
    start_date: str | None = None
    maturity_date: str | None = None
    invested: Amount
    current_value: Amount
    gain: Amount
    gain_pct: Amount
    status: str | None = None
    interest_received: Amount | None = None
    record: dict[str, Any]


class HoldingsTotals(BaseModel):
    invested: Amount
    current_value: Amount
    gain: Amount
    gain_pct: Amount


class TypeFacet(BaseModel):
    fd: int = 0
    rd: int = 0
    stock: int = 0
    bond: int = 0
    mf: int = 0


class StatusFacet(BaseModel):
    active: int = 0
    matured: int = 0


class HoldingsFacets(BaseModel):
    type: TypeFacet
    status: StatusFacet


class HoldingsResponse(BaseModel):
    items: list[HoldingRow]
    total: int
    page: int
    page_size: int
    page_count: int
    totals: HoldingsTotals
    facets: HoldingsFacets

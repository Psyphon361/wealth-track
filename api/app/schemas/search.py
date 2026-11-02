from datetime import datetime

from pydantic import BaseModel


class SearchTerms(BaseModel):
    ids: list[str]  # tickers and codes
    strong: list[str]  # issuer-like names
    weak: list[str]  # broker, platform, category, kind labels


class SearchItem(BaseModel):
    type: str
    type_label: str
    id: int
    title: str
    subtitle: str | None
    terms: SearchTerms
    notes: str | None
    current_value: float
    gain_pct: float | None
    status: str
    updated_at: datetime


class SearchIndexResponse(BaseModel):
    items: list[SearchItem]

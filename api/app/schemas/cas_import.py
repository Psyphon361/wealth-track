from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.schemas.assets import Dec
from app.schemas.messages import Outcome


class ExistingHolding(BaseModel):
    id: int
    units: Dec
    invested_amount: Dec
    avg_nav: Dec
    purchase_date: date


class CasTransaction(BaseModel):
    date: date
    type: Literal["purchase", "redemption"]
    amount: Dec
    units: Dec


class CasPreviewRow(BaseModel):
    key: str
    scheme_code: int | None
    scheme_name: str
    amc: str | None
    plan: Literal["direct", "regular"] | None
    option: Literal["growth", "idcw", "bonus", "other"] | None
    category: Literal["equity", "debt", "hybrid", "index", "elss", "liquid", "other"]
    isin: str | None
    folios: list[str]
    units: Dec
    invested_amount: Dec
    avg_nav: Dec
    purchase_date: date | None
    current_value: Dec | None
    existing: list[ExistingHolding]
    transactions: list[CasTransaction]
    importable: bool
    issue: str | None


class CasPreview(BaseModel):
    statement_from: date | None
    statement_to: date | None
    rows: list[CasPreviewRow]
    hidden_zero: int


class CasCommitRow(BaseModel):
    action: Literal["create", "update"]
    holding_id: int | None = None
    scheme_code: int
    scheme_name: str
    category: str
    units: Dec
    avg_nav: Dec
    invested_amount: Dec
    purchase_date: date
    transactions: list[CasTransaction] = []


class CasCommit(BaseModel):
    rows: list[CasCommitRow]


class CasCommitResult(Outcome):
    created: int
    updated: int

from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.portfolio import _q, load_group
from app.schemas.holdings import HoldingsResponse

router = APIRouter(tags=["holdings"])

PAGE_SIZE = 10
_ZERO = Decimal("0")

COMPOUNDING = ["monthly", "quarterly", "half_yearly", "yearly", "simple"]
STATUSES = ["active", "matured"]
BOND_TYPES = ["government", "corporate", "tax_free", "sgb", "other"]
MF_CATEGORIES = ["equity", "debt", "hybrid", "index", "elss", "liquid", "other"]

Compounding = Literal["monthly", "quarterly", "half_yearly", "yearly", "simple"]
Status = Literal["active", "matured"]
BondType = Literal["government", "corporate", "tax_free", "sgb", "other"]
MfCategory = Literal["equity", "debt", "hybrid", "index", "elss", "liquid", "other"]

# Per type: search fields, facets (key -> enum values, or None for free text),
# text sort keys (compared case-insensitively).
CONFIG: dict[str, dict[str, Any]] = {
    "fd": {
        "search": ("bank", "label", "notes"),
        "facets": {
            "bank": None,
            "payout_type": ["cumulative", "payout"],
            "compounding": COMPOUNDING,
            "status": STATUSES,
        },
        "text": {"bank", "compounding", "status"},
    },
    "rd": {
        "search": ("bank", "label", "notes"),
        "facets": {"bank": None, "status": STATUSES},
        "text": {"bank", "status"},
    },
    "stock": {
        "search": ("name", "symbol", "broker", "notes"),
        "facets": {"exchange": ["NSE", "BSE"], "broker": None},
        "text": {"name", "exchange", "broker"},
    },
    "bond": {
        "search": ("name", "isin", "issuer", "platform", "notes"),
        "facets": {
            "bond_type": BOND_TYPES,
            "issuer": None,
            "platform": None,
            "status": STATUSES,
        },
        "text": {"name", "issuer", "bond_type", "platform", "status"},
    },
    "mf": {
        "search": ("scheme_name", "platform", "notes"),
        "facets": {"category": MF_CATEGORIES, "platform": None},
        "text": {"scheme_name", "category", "platform"},
    },
}

FdSort = Literal[
    "bank", "principal", "rate", "compounding", "start_date", "maturity_date",
    "current_value", "gain", "gain_pct", "status",
]  # fmt: skip
RdSort = Literal[
    "bank", "monthly_instalment", "rate", "start_date", "maturity_date", "invested",
    "current_value", "gain", "gain_pct", "status",
]  # fmt: skip
StockSort = Literal[
    "name", "exchange", "broker", "quantity", "avg_buy_price", "invested",
    "current_value", "gain", "gain_pct", "buy_date",
]  # fmt: skip
BondSort = Literal[
    "name", "issuer", "bond_type", "platform", "quantity", "face_value", "purchase_price",
    "ytm", "purchase_date", "maturity_date", "invested", "current_value", "gain",
    "gain_pct", "status",
]  # fmt: skip
MfSort = Literal[
    "scheme_name", "category", "platform", "units", "avg_nav", "invested",
    "current_value", "gain", "gain_pct", "purchase_date",
]  # fmt: skip

Q = Annotated[str | None, Query(max_length=100)]
Dir = Literal["asc", "desc"]
Page = Annotated[int, Query(ge=1)]
Texts = Annotated[list[str] | None, Query()]


def _dec(value: Any) -> Decimal:
    return Decimal(str(value)) if value is not None else _ZERO


def _sort_value(item: dict[str, Any], key: str, text_keys: set[str]) -> Any:
    value = item.get(key)
    if value is not None and key in text_keys:
        return str(value).lower()
    return value


def _run(
    db: Session,
    slug: str,
    *,
    q: str | None,
    sort: str,
    dir: str,
    page: int,
    multi: dict[str, list[str] | None],
    range_field: str | None = None,
    range_min: Decimal | None = None,
    range_max: Decimal | None = None,
    maturity_from: date | None = None,
    maturity_to: date | None = None,
) -> dict[str, Any]:
    cfg = CONFIG[slug]
    rows: list[dict[str, Any]] = load_group(db, slug)["items"]
    needle = (q or "").strip().lower()
    selected = {k: set(v) for k, v in multi.items() if v}
    m_from = maturity_from.isoformat() if maturity_from else None
    m_to = maturity_to.isoformat() if maturity_to else None

    def passes(item: dict[str, Any], skip: str | None = None) -> bool:
        if needle and not any(
            needle in str(item[f]).lower() for f in cfg["search"] if item.get(f)
        ):
            return False
        for key, values in selected.items():
            if key != skip and item.get(key) not in values:
                return False
        if range_field and (range_min is not None or range_max is not None):
            value = item.get(range_field)
            if value is None:
                return False
            value = _dec(value)
            if range_min is not None and value < range_min:
                return False
            if range_max is not None and value > range_max:
                return False
        if m_from or m_to:
            maturity = item.get("maturity_date")
            if not maturity:
                return False
            if m_from and maturity < m_from:
                return False
            if m_to and maturity > m_to:
                return False
        return True

    filtered = [r for r in rows if passes(r)]

    facets: dict[str, list[dict[str, Any]]] = {}
    for key, enum_values in cfg["facets"].items():
        counts: dict[str, int] = {}
        for r in rows:
            value = r.get(key)
            if value in (None, "") or not passes(r, key):
                continue
            counts[value] = counts.get(value, 0) + 1
        if enum_values is not None:
            facets[key] = [{"value": v, "count": counts.get(v, 0)} for v in enum_values]
        else:
            # Distinct non-empty values present in the type (count may be 0 under other filters).
            present = {r[key] for r in rows if r.get(key) not in (None, "")}
            ordered = sorted(present, key=lambda v: (-counts.get(v, 0), v))
            facets[key] = [{"value": v, "count": counts.get(v, 0)} for v in ordered]

    invested = sum((_dec(r.get("invested")) for r in rows), _ZERO)
    current = sum((_dec(r.get("current_value")) for r in rows), _ZERO)
    gain = sum((_dec(r.get("gain")) for r in rows), _ZERO)
    summary = {
        "count": len(rows),
        "invested": _q(invested),
        "current_value": _q(current),
        "gain": _q(gain),
        "gain_pct": _q(gain / invested * 100) if invested else Decimal("0.00"),
    }

    # Stable tie-break by id, then sort by key; nulls always last.
    filtered.sort(key=lambda r: r["id"])
    text_keys = cfg["text"]
    with_value = [r for r in filtered if _sort_value(r, sort, text_keys) is not None]
    without = [r for r in filtered if _sort_value(r, sort, text_keys) is None]
    with_value.sort(key=lambda r: _sort_value(r, sort, text_keys), reverse=dir == "desc")
    ordered_rows = with_value + without

    total = len(ordered_rows)
    page_count = max(1, -(-total // PAGE_SIZE))
    page = min(page, page_count)
    start = (page - 1) * PAGE_SIZE
    return {
        "items": ordered_rows[start : start + PAGE_SIZE],
        "total": total,
        "page": page,
        "page_size": PAGE_SIZE,
        "page_count": page_count,
        "summary": summary,
        "facets": facets,
    }


@router.get("/holdings/fd", response_model=HoldingsResponse)
def get_fd_holdings(
    q: Q = None,
    bank: Texts = None,
    payout_type: Annotated[list[Literal["cumulative", "payout"]] | None, Query()] = None,
    compounding: Annotated[list[Compounding] | None, Query()] = None,
    status: Annotated[list[Status] | None, Query()] = None,
    rate_min: Decimal | None = None,
    rate_max: Decimal | None = None,
    maturity_from: date | None = None,
    maturity_to: date | None = None,
    sort: FdSort = "current_value",
    dir: Dir = "desc",
    page: Page = 1,
    db: Session = Depends(get_db),
):
    return _run(
        db, "fd", q=q, sort=sort, dir=dir, page=page,
        multi={"bank": bank, "payout_type": payout_type, "compounding": compounding, "status": status},
        range_field="rate", range_min=rate_min, range_max=rate_max,
        maturity_from=maturity_from, maturity_to=maturity_to,
    )  # fmt: skip


@router.get("/holdings/rd", response_model=HoldingsResponse)
def get_rd_holdings(
    q: Q = None,
    bank: Texts = None,
    status: Annotated[list[Status] | None, Query()] = None,
    rate_min: Decimal | None = None,
    rate_max: Decimal | None = None,
    maturity_from: date | None = None,
    maturity_to: date | None = None,
    sort: RdSort = "current_value",
    dir: Dir = "desc",
    page: Page = 1,
    db: Session = Depends(get_db),
):
    return _run(
        db, "rd", q=q, sort=sort, dir=dir, page=page,
        multi={"bank": bank, "status": status},
        range_field="rate", range_min=rate_min, range_max=rate_max,
        maturity_from=maturity_from, maturity_to=maturity_to,
    )  # fmt: skip


@router.get("/holdings/stock", response_model=HoldingsResponse)
def get_stock_holdings(
    q: Q = None,
    exchange: Annotated[list[Literal["NSE", "BSE"]] | None, Query()] = None,
    broker: Texts = None,
    sort: StockSort = "current_value",
    dir: Dir = "desc",
    page: Page = 1,
    db: Session = Depends(get_db),
):
    return _run(
        db, "stock", q=q, sort=sort, dir=dir, page=page,
        multi={"exchange": exchange, "broker": broker},
    )  # fmt: skip


@router.get("/holdings/bond", response_model=HoldingsResponse)
def get_bond_holdings(
    q: Q = None,
    bond_type: Annotated[list[BondType] | None, Query()] = None,
    issuer: Texts = None,
    platform: Texts = None,
    status: Annotated[list[Status] | None, Query()] = None,
    ytm_min: Decimal | None = None,
    ytm_max: Decimal | None = None,
    maturity_from: date | None = None,
    maturity_to: date | None = None,
    sort: BondSort = "current_value",
    dir: Dir = "desc",
    page: Page = 1,
    db: Session = Depends(get_db),
):
    return _run(
        db, "bond", q=q, sort=sort, dir=dir, page=page,
        multi={"bond_type": bond_type, "issuer": issuer, "platform": platform, "status": status},
        range_field="ytm", range_min=ytm_min, range_max=ytm_max,
        maturity_from=maturity_from, maturity_to=maturity_to,
    )  # fmt: skip


@router.get("/holdings/mf", response_model=HoldingsResponse)
def get_mf_holdings(
    q: Q = None,
    category: Annotated[list[MfCategory] | None, Query()] = None,
    platform: Texts = None,
    sort: MfSort = "current_value",
    dir: Dir = "desc",
    page: Page = 1,
    db: Session = Depends(get_db),
):
    return _run(
        db, "mf", q=q, sort=sort, dir=dir, page=page,
        multi={"category": category, "platform": platform},
    )  # fmt: skip

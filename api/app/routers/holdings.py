from datetime import date
from enum import IntEnum
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.portfolio import _q, load_groups
from app.schemas.holdings import AssetType, HoldingsResponse, HoldingStatus

router = APIRouter(tags=["holdings"])

TYPE_ORDER = {"fd": 0, "rd": 1, "stock": 2, "bond": 3, "mf": 4}
MF_CATEGORIES = {
    "equity": "Equity",
    "debt": "Debt",
    "hybrid": "Hybrid",
    "index": "Index",
    "elss": "ELSS",
    "liquid": "Liquid",
    "other": "Other",
}
SEARCH_FIELDS = (
    "name",
    "bank",
    "label",
    "symbol",
    "isin",
    "issuer",
    "scheme_name",
    "broker",
    "platform",
    "notes",
)
SortKey = Literal[
    "name",
    "type",
    "invested",
    "current_value",
    "gain",
    "gain_pct",
    "start_date",
    "maturity_date",
    "status",
]
_ZERO = Decimal("0")


class PageSize(IntEnum):
    ten = 10
    twenty_five = 25
    fifty = 50
    hundred = 100


def _dec(value: Any) -> Decimal:
    return Decimal(str(value)) if value is not None else _ZERO


def _row(slug: str, item: dict[str, Any]) -> dict[str, Any]:
    if slug in ("fd", "rd"):
        name, detail, start = item["bank"], item.get("label"), item["start_date"]
    elif slug == "stock":
        symbol = item.get("symbol")
        exchange = item.get("exchange")
        name = item["name"]
        detail = f"{symbol} · {exchange}" if symbol else exchange
        start = item["buy_date"]
    elif slug == "bond":
        name, detail, start = item["name"], item.get("issuer"), item["purchase_date"]
    else:
        category = item.get("category")
        name = item["scheme_name"]
        detail = MF_CATEGORIES.get(category, category)
        start = item["purchase_date"]
    return {
        "id": item["id"],
        "type": slug,
        "name": name,
        "detail": detail,
        "start_date": start,
        "maturity_date": item.get("maturity_date"),
        "invested": _dec(item.get("invested")),
        "current_value": _dec(item.get("current_value")),
        "gain": _dec(item.get("gain")),
        "gain_pct": _dec(item.get("gain_pct")),
        "status": item.get("status"),
        "interest_received": _dec(item["interest_received"])
        if item.get("interest_received") is not None
        else None,
        "record": item,
    }


def _search_text(row: dict[str, Any]) -> str:
    record = row["record"]
    return "\n".join(str(record[f]).lower() for f in SEARCH_FIELDS if record.get(f))


def _sort_value(row: dict[str, Any], key: str) -> Any:
    if key == "name":
        return row["name"].lower()
    if key == "type":
        return TYPE_ORDER[row["type"]]
    return row[key]


@router.get("/holdings", response_model=HoldingsResponse)
def get_holdings(
    q: Annotated[str | None, Query(max_length=100)] = None,
    type: Annotated[list[AssetType] | None, Query()] = None,
    status: Annotated[list[HoldingStatus] | None, Query()] = None,
    gain: Literal["gainers", "losers", "flat"] | None = None,
    invested_min: Annotated[Decimal | None, Query(ge=0)] = None,
    invested_max: Annotated[Decimal | None, Query(ge=0)] = None,
    maturity_from: date | None = None,
    maturity_to: date | None = None,
    sort: SortKey = "current_value",
    dir: Literal["asc", "desc"] = "desc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: PageSize = PageSize.twenty_five,
    db: Session = Depends(get_db),
):
    needle = (q or "").strip().lower()
    types = set(type) if type else None
    statuses = set(status) if status else None
    page_size = int(page_size)
    m_from = maturity_from.isoformat() if maturity_from else None
    m_to = maturity_to.isoformat() if maturity_to else None

    rows = [
        _row(g["type"], item) for g in load_groups(db) for item in g["items"]
    ]

    def passes(row: dict[str, Any], skip: str | None = None) -> bool:
        if needle and needle not in _search_text(row):
            return False
        if skip != "type" and types is not None and row["type"] not in types:
            return False
        if skip != "status" and statuses is not None and row["status"] not in statuses:
            return False
        if gain == "gainers" and not row["gain"] > 0:
            return False
        if gain == "losers" and not row["gain"] < 0:
            return False
        if gain == "flat" and row["gain"] != 0:
            return False
        if invested_min is not None and row["invested"] < invested_min:
            return False
        if invested_max is not None and row["invested"] > invested_max:
            return False
        if m_from or m_to:
            maturity = row["maturity_date"]
            if not maturity:
                return False
            if m_from and maturity < m_from:
                return False
            if m_to and maturity > m_to:
                return False
        return True

    filtered = [r for r in rows if passes(r)]

    facets = {
        "type": {t: 0 for t in TYPE_ORDER},
        "status": {"active": 0, "matured": 0},
    }
    for r in rows:
        if passes(r, "type"):
            facets["type"][r["type"]] += 1
        if passes(r, "status") and r["status"] in facets["status"]:
            facets["status"][r["status"]] += 1

    invested = sum((r["invested"] for r in filtered), _ZERO)
    current = sum((r["current_value"] for r in filtered), _ZERO)
    total_gain = sum((r["gain"] for r in filtered), _ZERO)
    totals = {
        "invested": _q(invested),
        "current_value": _q(current),
        "gain": _q(total_gain),
        "gain_pct": _q(total_gain / invested * 100) if invested else Decimal("0.00"),
    }

    # Stable tie-break by (type order, id), then sort by key; nulls always last.
    filtered.sort(key=lambda r: (TYPE_ORDER[r["type"]], r["id"]))
    reverse = dir == "desc"
    with_value = [r for r in filtered if _sort_value(r, sort) is not None]
    without = [r for r in filtered if _sort_value(r, sort) is None]
    with_value.sort(key=lambda r: _sort_value(r, sort), reverse=reverse)
    ordered = with_value + without

    total = len(ordered)
    page_count = max(1, -(-total // page_size))
    page = min(page, page_count)
    start = (page - 1) * page_size
    return {
        "items": ordered[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "page_count": page_count,
        "totals": totals,
        "facets": facets,
    }

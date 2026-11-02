from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models.mf_transaction import MFTransaction
from app.models.user import User
from app.routers.portfolio import _q, load_group, load_holding
from app.schemas.holdings import HoldingDetailResponse, HoldingsResponse
from app.schemas.market_master import (
    BondMasterRead,
    FdIssuerRead,
    NpsMasterRead,
    StockMasterRead,
)
from app.schemas.mf_scheme import MFSchemeRead
from app.services import amfi, bond_master, fd_issuers, nps, stock_master, valuation

router = APIRouter(tags=["holdings"])

PAGE_SIZE = 10
_ZERO = Decimal("0")

COMPOUNDING = ["monthly", "quarterly", "half_yearly", "yearly", "simple"]
STATUSES = ["active", "matured"]
BOND_TYPES = ["government", "corporate", "tax_free", "sgb", "other"]
GOLD_FORMS = ["jewellery", "coin", "bar", "digital"]
GOLD_METALS = ["gold", "silver"]
GOLD_PURITIES = ["999", "995", "916", "750", "585", "925"]
CASH_KINDS = ["savings", "current", "cash", "other"]
PF_KINDS = ["epf", "vpf", "ppf"]
NPS_TIERS = ["I", "II"]
NPS_ASSET_CLASSES = ["E", "C", "G", "A", "other"]
MF_CATEGORIES = ["equity", "debt", "hybrid", "index", "elss", "liquid", "other"]

Compounding = Literal["monthly", "quarterly", "half_yearly", "yearly", "simple"]
Status = Literal["active", "matured"]
BondType = Literal["government", "corporate", "tax_free", "sgb", "other"]
GoldForm = Literal["jewellery", "coin", "bar", "digital"]
GoldMetal = Literal["gold", "silver"]
GoldPurity = Literal["999", "995", "916", "750", "585", "925"]
CashKind = Literal["savings", "current", "cash", "other"]
PfKind = Literal["epf", "vpf", "ppf"]
NpsTier = Literal["I", "II"]
NpsAssetClass = Literal["E", "C", "G", "A", "other"]
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
    "nps": {
        "search": ("scheme_name", "notes"),
        "facets": {"pfm_name": None, "tier": NPS_TIERS, "asset_class": NPS_ASSET_CLASSES},
        "text": {"scheme_name", "pfm_name", "tier", "asset_class"},
    },
    "gold": {
        "search": ("name", "notes"),
        "facets": {"form": GOLD_FORMS, "metal": GOLD_METALS, "purity": GOLD_PURITIES},
        "text": {"name", "form", "metal", "purity"},
    },
    "cash": {
        "search": ("name", "notes"),
        "facets": {"kind": CASH_KINDS},
        "text": {"name", "kind"},
    },
    "pf": {
        "search": ("name", "notes"),
        "facets": {"kind": PF_KINDS},
        "text": {"name", "kind"},
    },
    "other": {
        "search": ("name", "category"),
        "facets": {"category": None},
        "text": {"name", "category"},
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
    "current_value", "gain", "gain_pct", "xirr", "purchase_date",
]  # fmt: skip

NpsSort = Literal[
    "scheme_name", "pfm_name", "tier", "asset_class", "units", "nav", "contributed",
    "current_value", "gain", "gain_pct", "start_date",
]  # fmt: skip

GoldSort = Literal[
    "name", "form", "metal", "purity", "weight_grams", "purchase_date", "invested",
    "current_value", "gain", "gain_pct", "xirr",
]  # fmt: skip

CashSort = Literal["name", "kind", "balance_date", "current_value", "interest_rate"]

PfSort = Literal[
    "name", "kind", "balance_date", "current_value", "interest_rate", "maturity_date"
]

OtherSort = Literal[
    "name", "category", "current_value", "invested", "gain", "value_date"
]

Q =Annotated[str | None, Query(max_length=100)]
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


def add_mf_xirr(db: Session, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Items with xirr, xirr_basis and xirr_transactions added (one transactions query)."""
    by_holding: dict[int, list[MFTransaction]] = {}
    if items:
        rows = db.scalars(
            select(MFTransaction)
            .where(MFTransaction.mutual_fund_id.in_([i["id"] for i in items]))
            .order_by(MFTransaction.txn_date, MFTransaction.id)
        ).all()
        for t in rows:
            by_holding.setdefault(t.mutual_fund_id, []).append(t)
    enriched = []
    for item in items:
        pct, basis, used = valuation.mf_xirr(
            _dec(item["units"]), _dec(item["invested_amount"]), item["purchase_date"],
            _dec(item["current_value"]), by_holding.get(item["id"], []),
            item.get("nav_date") or date.today(),
        )  # fmt: skip
        enriched.append({
            **item,
            "xirr": float(pct) + 0.0 if pct is not None else None,
            "xirr_basis": basis,
            "xirr_transactions": used,
        })
    return enriched


def _canonical_categories(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group categories case-insensitively: each shows the spelling of its newest holding."""
    newest: dict[str, str] = {}
    for item in sorted(items, key=lambda i: i["id"]):
        newest[item["category"].strip().lower()] = item["category"]
    return [{**i, "category": newest[i["category"].strip().lower()]} for i in items]


def _run(
    db: Session,
    user_id: int,
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
    group = load_group(db, slug, user_id)
    rows: list[dict[str, Any]] = group["items"]
    if slug == "mf":
        rows = add_mf_xirr(db, rows)
    if slug == "other":
        rows = _canonical_categories(rows)
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

    # Totals cover active holdings only; matured rows are listed but excluded.
    active_rows = [r for r in rows if r.get("status", "active") == "active"]
    invested = sum((_dec(r.get("invested")) for r in active_rows), _ZERO)
    current = sum((_dec(r.get("current_value")) for r in active_rows), _ZERO)
    gain = sum((_dec(r.get("gain")) for r in active_rows), _ZERO)
    # The % base is the invested of rows that have a gain (Other without invested has none).
    gain_base = sum(
        (_dec(r.get("invested")) for r in active_rows if r.get("gain") is not None), _ZERO
    )
    summary = {
        "count": len(active_rows),
        "matured_count": len(rows) - len(active_rows),
        "invested": _q(invested),
        "current_value": _q(current),
        "gain": _q(gain),
        "gain_pct": _q(gain / gain_base * 100) if gain_base else Decimal("0.00"),
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
        "prices_as_of": group.get("prices_as_of"),
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
    user: User = Depends(current_user),
):
    return _run(
        db, user.id, "fd",q=q, sort=sort, dir=dir, page=page,
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
    user: User = Depends(current_user),
):
    return _run(
        db, user.id, "rd",q=q, sort=sort, dir=dir, page=page,
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
    user: User = Depends(current_user),
):
    return _run(
        db, user.id, "stock",q=q, sort=sort, dir=dir, page=page,
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
    user: User = Depends(current_user),
):
    return _run(
        db, user.id, "bond",q=q, sort=sort, dir=dir, page=page,
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
    user: User = Depends(current_user),
):
    return _run(
        db, user.id, "mf",q=q, sort=sort, dir=dir, page=page,
        multi={"category": category, "platform": platform},
    )  # fmt: skip


@router.get("/holdings/nps", response_model=HoldingsResponse)
def get_nps_holdings(
    q: Q = None,
    pfm_name: Texts = None,
    tier: Annotated[list[NpsTier] | None, Query()] = None,
    asset_class: Annotated[list[NpsAssetClass] | None, Query()] = None,
    sort: NpsSort = "current_value",
    dir: Dir = "desc",
    page: Page = 1,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return _run(
        db, user.id, "nps", q=q, sort=sort, dir=dir, page=page,
        multi={"pfm_name": pfm_name, "tier": tier, "asset_class": asset_class},
    )  # fmt: skip


@router.get("/holdings/gold", response_model=HoldingsResponse)
def get_gold_holdings(
    q: Q = None,
    form: Annotated[list[GoldForm] | None, Query()] = None,
    metal: Annotated[list[GoldMetal] | None, Query()] = None,
    purity: Annotated[list[GoldPurity] | None, Query()] = None,
    sort: GoldSort = "current_value",
    dir: Dir = "desc",
    page: Page = 1,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return _run(
        db, user.id, "gold",q=q, sort=sort, dir=dir, page=page,
        multi={"form": form, "metal": metal, "purity": purity},
    )  # fmt: skip


@router.get("/holdings/cash", response_model=HoldingsResponse)
def get_cash_holdings(
    q: Q = None,
    kind: Annotated[list[CashKind] | None, Query()] = None,
    sort: CashSort = "current_value",
    dir: Dir = "desc",
    page: Page = 1,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return _run(
        db, user.id, "cash", q=q, sort=sort, dir=dir, page=page,
        multi={"kind": kind},
    )  # fmt: skip


@router.get("/holdings/pf", response_model=HoldingsResponse)
def get_pf_holdings(
    q: Q = None,
    kind: Annotated[list[PfKind] | None, Query()] = None,
    sort: PfSort = "current_value",
    dir: Dir = "desc",
    page: Page = 1,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return _run(
        db, user.id, "pf", q=q, sort=sort, dir=dir, page=page,
        multi={"kind": kind},
    )  # fmt: skip


@router.get("/holdings/other", response_model=HoldingsResponse)
def get_other_holdings(
    q: Q = None,
    category: Texts = None,
    sort: OtherSort = "current_value",
    dir: Dir = "desc",
    page: Page = 1,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return _run(
        db, user.id, "other", q=q, sort=sort, dir=dir, page=page,
        multi={"category": category},
    )  # fmt: skip


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "message": "Holding not found",
            "description": "It may have been deleted, or it belongs to another account.",
        },
    )


def linked_master(db: Session, slug: str, record: Any) -> dict[str, Any] | None:
    """The master record linked to a holding, serialised with its read model."""
    if slug in ("fd", "rd"):
        found = fd_issuers.get_issuer(db, record.issuer_id) if record.issuer_id else None
        schema = FdIssuerRead
    elif slug == "stock":
        found = stock_master.get_stock_master(db, record.master_id) if record.master_id else None
        schema = StockMasterRead
    elif slug == "bond":
        found = bond_master.get_bond_master(db, record.master_id) if record.master_id else None
        schema = BondMasterRead
    elif slug in ("gold", "cash", "pf", "other"):
        return None  # no master table
    elif slug == "nps":
        found = nps.get_scheme_with_nav(db, record.scheme_id)
        schema = NpsMasterRead
    else:
        found = amfi.get_scheme_with_nav(db, record.scheme_code) if record.scheme_code else None
        schema = MFSchemeRead
    return schema.model_validate(found).model_dump(mode="json") if found is not None else None


@router.get("/holdings/{slug}/{item_id}", response_model=HoldingDetailResponse)
def get_holding_detail(
    slug: str,
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if slug not in CONFIG:
        raise _not_found()
    loaded = load_holding(db, slug, user.id, item_id)
    if loaded is None:
        raise _not_found()
    record, item = loaded
    if slug == "mf":
        item = add_mf_xirr(db, [item])[0]
    return {"item": item, "master": linked_master(db, slug, record)}

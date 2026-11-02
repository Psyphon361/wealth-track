"""Search index for the global search palette: one flat item per holding, ranked in the browser.

`build_items` is pure (valued groups from `load_groups` + master rows in, items out); the
`fetch_*` helpers read only the master rows the user's holdings link to, one query per master.
"""

from types import SimpleNamespace
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.bond import Bond
from app.models.bond_master import BondMaster
from app.models.fd_issuer_master import FdIssuerMaster
from app.models.fixed_deposit import FixedDeposit
from app.models.mf_master import MFMaster
from app.models.mutual_fund import MutualFund
from app.models.recurring_deposit import RecurringDeposit
from app.models.stock import Stock
from app.models.stock_master import StockMaster
from app.routers.assets import _holding_name

# Human labels, same wording as web/lib/types.ts.
BOND_TYPE_LABELS = {
    "government": "Government",
    "corporate": "Corporate",
    "tax_free": "Tax-free",
    "sgb": "SGB",
    "other": "Other",
}
MF_CATEGORY_LABELS = {
    "equity": "Equity",
    "debt": "Debt",
    "hybrid": "Hybrid",
    "index": "Index",
    "elss": "ELSS",
    "liquid": "Liquid",
    "other": "Other",
}
CASH_KIND_LABELS = {
    "savings": "Savings account",
    "current": "Current account",
    "cash": "Cash in hand",
    "other": "Other",
}
PF_KIND_LABELS = {"epf": "EPF", "vpf": "VPF", "ppf": "PPF"}
GOLD_METAL_LABELS = {"gold": "Gold", "silver": "Silver"}
GOLD_FORM_LABELS = {"jewellery": "Jewellery", "coin": "Coin", "bar": "Bar", "digital": "Digital"}
GOLD_PURITY_LABELS = {
    "999": "24K (999)",
    "995": "24K (995)",
    "916": "22K (916)",
    "750": "18K (750)",
    "585": "14K (585)",
    "925": "925 (sterling)",
}


def _purity_label(metal: str, purity: str) -> str:
    # 999 reads differently for gold (24K) and silver (fine).
    if metal == "silver" and purity == "999":
        return "999 (fine)"
    return GOLD_PURITY_LABELS.get(purity, purity)


def _label(labels: dict[str, str], value: str | None) -> str | None:
    return labels.get(value, value) if value else None


def _rate(rate: float | None) -> str | None:
    return f"{rate:g}% p.a." if rate is not None else None


def _clean(parts: list[Any]) -> list[str]:
    return [p.strip() for p in parts if isinstance(p, str) and p.strip()]


def _dedupe(parts: list[Any], taken: set[str]) -> list[str]:
    """Non-empty strings in order, skipping any already in `taken` (case-insensitive)."""
    out = []
    for part in _clean(parts):
        key = part.lower()
        if key not in taken:
            taken.add(key)
            out.append(part)
    return out


def _parts(item: dict[str, Any], masters: dict[str, dict[Any, Any]]) -> tuple[list, list, list, list]:
    """(subtitle parts, ids, strong, weak) for one holding, before cleaning."""
    stock = masters["stock"].get(item.get("master_id")) if item["type"] == "stock" else None
    bond = masters["bond"].get(item.get("master_id")) if item["type"] == "bond" else None
    fund = masters["mf"].get(item.get("scheme_code")) if item["type"] == "mf" else None
    issuer = masters["issuer"].get(item.get("issuer_id")) if item["type"] in ("fd", "rd") else None
    match item["type"]:
        case "fd" | "rd":
            return (
                [_rate(item.get("rate"))],
                [],
                [item["bank"], issuer.short_name if issuer else None],
                [],
            )
        case "stock":
            return (
                [item.get("symbol"), item.get("exchange"), item.get("broker")],
                [
                    item.get("symbol"),
                    *((stock.nse_symbol, stock.bse_symbol, stock.bse_code, stock.isin) if stock else ()),
                ],
                [],
                [item.get("broker")],
            )
        case "bond":
            bond_type = _label(BOND_TYPE_LABELS, item.get("bond_type"))
            return (
                [item.get("issuer"), bond_type],
                [item.get("isin"), bond.nse_symbol if bond else None],
                [item.get("issuer")],
                [item.get("platform"), bond_type],
            )
        case "mf":
            category = _label(MF_CATEGORY_LABELS, item.get("category"))
            amc = fund.amc if fund else None
            return (
                [amc, category],
                [
                    str(item["scheme_code"]) if item.get("scheme_code") is not None else None,
                    *((fund.isin_growth_payout, fund.isin_reinvest) if fund else ()),
                ],
                [amc],
                [item.get("platform"), category],
            )
        case "nps":
            tier = f"Tier {item['tier']}" if item.get("tier") else None
            return ([item.get("pfm_name"), tier], [item.get("scheme_id")], [item.get("pfm_name")], [])
        case "gold":
            metal = _label(GOLD_METAL_LABELS, item.get("metal"))
            form = _label(GOLD_FORM_LABELS, item.get("form"))
            purity = _purity_label(item.get("metal", ""), item.get("purity", ""))
            return ([metal, form, purity], [], [], [metal, form, purity, item.get("purity")])
        case "cash" | "pf":
            kinds = CASH_KIND_LABELS if item["type"] == "cash" else PF_KIND_LABELS
            kind = _label(kinds, item.get("kind"))
            return ([kind], [], [], [kind])
        case _:
            return ([item.get("category")], [], [], [item.get("category")])


def build_items(
    groups: list[dict[str, Any]], masters: dict[str, dict[Any, Any]]
) -> list[dict[str, Any]]:
    """One search item per valued holding, in group (REGISTRY) order then id order.

    `masters` maps "stock" (by id), "bond" (by id), "mf" (by scheme_code) and "issuer"
    (by id) to the master rows the holdings link to; unlinked holdings simply find none.
    """
    out = []
    for group in groups:
        for raw in group["items"]:
            item = {**raw, "type": group["type"]}
            title = _holding_name(SimpleNamespace(**item))
            subtitle, ids, strong, weak = _parts(item, masters)
            taken = {title.lower()}
            out.append(
                {
                    "type": group["type"],
                    "type_label": group["label"],
                    "id": item["id"],
                    "title": title,
                    "subtitle": " · ".join(_clean(subtitle)) or None,
                    "terms": {
                        "ids": _dedupe(ids, taken),
                        "strong": _dedupe(strong, taken),
                        "weak": _dedupe(weak, taken),
                    },
                    "notes": item.get("notes"),
                    "current_value": item["current_value"],
                    "gain_pct": item.get("gain_pct"),
                    "status": item["status"],
                    "updated_at": item["updated_at"],
                }
            )
    return out


def _rows(bind: Any, stmt: Any, key: str) -> dict[Any, Any]:
    """Rows of `stmt` keyed by column `key`, on this part's own session."""
    with Session(bind, autoflush=False, expire_on_commit=False) as session:
        return {getattr(row, key): row for row in session.execute(stmt)}


def fetch_stock_masters(bind: Any, user_id: int) -> dict[int, Any]:
    held = select(Stock.master_id).where(Stock.user_id == user_id, Stock.master_id.is_not(None))
    stmt = select(
        StockMaster.id,
        StockMaster.isin,
        StockMaster.nse_symbol,
        StockMaster.bse_symbol,
        StockMaster.bse_code,
    ).where(StockMaster.id.in_(held))
    return _rows(bind, stmt, "id")


def fetch_bond_masters(bind: Any, user_id: int) -> dict[int, Any]:
    held = select(Bond.master_id).where(Bond.user_id == user_id, Bond.master_id.is_not(None))
    stmt = select(BondMaster.id, BondMaster.nse_symbol).where(BondMaster.id.in_(held))
    return _rows(bind, stmt, "id")


def fetch_mf_masters(bind: Any, user_id: int) -> dict[int, Any]:
    held = select(MutualFund.scheme_code).where(
        MutualFund.user_id == user_id, MutualFund.scheme_code.is_not(None)
    )
    stmt = select(
        MFMaster.scheme_code, MFMaster.amc, MFMaster.isin_growth_payout, MFMaster.isin_reinvest
    ).where(MFMaster.scheme_code.in_(held))
    return _rows(bind, stmt, "scheme_code")


def fetch_issuer_masters(bind: Any, user_id: int) -> dict[int, Any]:
    fds = select(FixedDeposit.issuer_id).where(
        FixedDeposit.user_id == user_id, FixedDeposit.issuer_id.is_not(None)
    )
    rds = select(RecurringDeposit.issuer_id).where(
        RecurringDeposit.user_id == user_id, RecurringDeposit.issuer_id.is_not(None)
    )
    stmt = select(FdIssuerMaster.id, FdIssuerMaster.short_name).where(
        or_(FdIssuerMaster.id.in_(fds), FdIssuerMaster.id.in_(rds))
    )
    return _rows(bind, stmt, "id")


# One entry per master table; the router runs them concurrently with load_groups.
MASTER_FETCHERS = {
    "stock": fetch_stock_masters,
    "bond": fetch_bond_masters,
    "mf": fetch_mf_masters,
    "issuer": fetch_issuer_masters,
}

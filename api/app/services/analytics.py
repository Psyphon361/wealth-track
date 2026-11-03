"""Portfolio analytics maths: asset-class allocation, concentration, the liquidity ladder, the
maturity calendar, bank safety (DICGC) and data health.

Pure functions over the valued groups from `routers.portfolio.build_groups` / `load_groups`
(a list of {type, label, items}; every item is the read schema plus the computed fields, as JSON
floats and ISO date strings). Master data comes in as plain lookup dicts keyed by master id, MF
scheme_code, or issuer id, so nothing here touches the DB or the clock: `today` is a parameter.

Only holdings with status "active" count (matured ones are excluded from every total, as on the
dashboard). Money is summed unrounded in Decimal (floats go through str) and rounded once, to 2 dp
ROUND_HALF_UP; percentages are rounded to 2 dp. An empty portfolio or a zero denominator gives
zeros and empty lists, never an error.

Lookup shapes (a Mapping or any object with these attributes; missing entries are fine):
  stock_masters  {stock_master.id: kind ("stock" | "etf"), name}
  bond_masters   {bond_master.id: bond_type, issuer}
  mf_masters     {mf_master.scheme_code: amc, amfi_category, name}
  issuer_masters {fd_issuer_master.id: name, short_name, merged_into_id}
  mf_transactions {mutual_funds.id: [{txn_date, kind "purchase" | "redemption", units}, ...]}
"""

import re
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace
from typing import Any, NamedTuple

from dateutil.relativedelta import relativedelta

from app.routers.assets import _holding_name
from app.services import valuation

CLASSES = ("equity", "debt", "hybrid", "gold", "cash", "other")
CLASS_LABELS = {
    "equity": "Equity",
    "debt": "Debt",
    "hybrid": "Hybrid",
    "gold": "Gold & silver",
    "cash": "Cash",
    "other": "Other",
}
BUCKETS = (
    ("instant", "Instant"),
    ("days", "1-3 days"),
    ("breakable", "Breakable"),
    ("illiquid", "Illiquid"),
    ("locked", "Locked"),
    ("not_classified", "Not classified"),
)
TOP_HOLDINGS = 10
STOCK_FLAG_PCT = Decimal(10)
AMC_FLAG_PCT = Decimal(30)
ELSS_LOCK_YEARS = 3
COMING_UP_DAYS = 90
DICGC_LIMIT = Decimal(500000)
STALE_MONTHS = 6

_CENT = Decimal("0.01")
_ZERO = Decimal(0)
_HUNDRED = Decimal(100)
_NPS_CLASS = {"E": "equity", "C": "debt", "G": "debt", "A": "debt"}
# Holding's own MF category (manual entries without a linked scheme) -> asset class.
_MF_CATEGORY_CLASS = {
    "equity": "equity",
    "elss": "equity",
    "index": "equity",
    "debt": "debt",
    "liquid": "debt",
    "hybrid": "hybrid",
}


# --- Small helpers -----------------------------------------------------------------------------


def _q(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _dec(value: Any) -> Decimal:
    return Decimal(str(value)) if value is not None else _ZERO


def _pct(value: Decimal, total: Decimal) -> Decimal:
    return _q(value * _HUNDRED / total) if total else Decimal("0.00")


def _field(obj: Any, name: str) -> Any:
    """`name` from a Mapping or an attribute object (a DB row); None when absent."""
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _to_date(value: Any) -> date | None:
    """A date, or the date part of an ISO string; None when empty or unreadable."""
    if not value:
        return None
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return value if isinstance(value, date) else None


def _norm(text: Any) -> str:
    """Trimmed, whitespace-collapsed, case-insensitive key for entered names."""
    return " ".join(str(text or "").split()).casefold()


def _clean(text: Any) -> str:
    return " ".join(str(text or "").split())


def _item_name(item: Mapping[str, Any]) -> str:
    """Display name of a valued item (an FD reads "Bank · label", an MF its scheme name)."""
    return _holding_name(SimpleNamespace(**{"label": None, **item}))


# --- Name rules (ETFs and index funds) ---------------------------------------------------------

_TOKEN = re.compile(r"[A-Z0-9]+")
_GOLD_TOKENS = frozenset({"GOLD", "SILVER", "GOLDBEES", "SILVERBEES", "GOLDETF", "SILVERETF"})
_DEBT_TOKENS = frozenset(
    {
        "LIQUID", "LIQUIDBEES", "LIQUIDCASE", "OVERNIGHT", "ARBITRAGE",
        "GILT", "GILTS", "SDL", "SDLS", "BOND", "BONDS", "BHARATBOND", "GSEC", "TBILL",
        "DEBT", "INCOME",
    }
)  # fmt: skip
_DEBT_PHRASES = ("BHARAT BOND", "TARGET MATURITY", "MONEY MARKET", "G SEC", "T BILL", "TREASURY BILL")
_EQUITY_TOKENS = frozenset({"NIFTY", "SENSEX"})
_ETF_CATEGORY = re.compile(r"\betfs?\b")
_FOF_CATEGORY = re.compile(r"\bfof\b")


def classify_by_name(name: str | None, default: str | None = None) -> str | None:
    """Asset class from a fund or ETF name, matching whole tokens, in this order:
    gold/silver -> gold; liquid, bond, gilt, SDL, target maturity and the like -> debt (so a
    "Nifty SDL" or target-maturity index fund is debt, not equity); NIFTY/SENSEX -> equity;
    otherwise `default`.
    """
    tokens = _TOKEN.findall((name or "").upper())
    joined = f" {' '.join(tokens)} "
    if _GOLD_TOKENS.intersection(tokens):
        return "gold"
    if _DEBT_TOKENS.intersection(tokens) or any(f" {p} " in joined for p in _DEBT_PHRASES):
        return "debt"
    if _EQUITY_TOKENS.intersection(tokens):
        return "equity"
    return default


# --- Classification ----------------------------------------------------------------------------


def _norm_amfi_category(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    for prefix in ("close ended - ", "interval - "):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text


def is_elss(item: Mapping[str, Any], fund: Any) -> bool:
    """ELSS by the AMFI category when the scheme is linked, else by the holding's own category."""
    category = _norm_amfi_category(_field(fund, "amfi_category"))
    if category:
        return "elss" in category
    return item.get("category") == "elss"


def _stock_class(item: Mapping[str, Any], master: Any) -> str:
    if _field(master, "kind") == "etf":
        return classify_by_name(_field(master, "name") or item.get("name"), "equity") or "equity"
    return "equity"


def _mf_class(item: Mapping[str, Any], fund: Any) -> str:
    name = _field(fund, "name") or item.get("scheme_name")
    category = _norm_amfi_category(_field(fund, "amfi_category"))
    if category:
        if "elss" in category or category.startswith("equity scheme"):
            return "equity"
        if "arbitrage" in category:
            return "debt"
        if category.startswith("hybrid scheme"):
            return "hybrid"
        if category.startswith(("debt scheme", "income/debt")):
            return "debt"
        if "gold" in category or "silver" in category:
            return "gold"
        if "overseas" in category:
            return "equity"
        if "index fund" in category or _ETF_CATEGORY.search(category):
            return classify_by_name(name, "equity") or "equity"
        # Domestic fund of funds (overseas and gold were handled above) and solution-oriented
        # schemes (retirement, children's) hold a mix: name rules, then hybrid.
        if _FOF_CATEGORY.search(category) or "solution oriented" in category:
            return classify_by_name(name, "hybrid") or "hybrid"
    # No linked scheme, or a category with no rule: name rules, then the holding's own category.
    return classify_by_name(name) or _MF_CATEGORY_CLASS.get(item.get("category"), "other")


def classify_holding(
    asset_type: str,
    item: Mapping[str, Any],
    *,
    stock_masters: Mapping[Any, Any] | None = None,
    bond_masters: Mapping[Any, Any] | None = None,
    mf_masters: Mapping[Any, Any] | None = None,
) -> str:
    """Asset class (equity, debt, hybrid, gold, cash, other) of one holding."""
    if asset_type == "stock":
        return _stock_class(item, (stock_masters or {}).get(item.get("master_id")))
    if asset_type == "mf":
        return _mf_class(item, (mf_masters or {}).get(item.get("scheme_code")))
    if asset_type == "bond":
        master = (bond_masters or {}).get(item.get("master_id"))
        if item.get("bond_type") == "sgb" or _field(master, "bond_type") == "sgb":
            return "gold"
        return "debt"
    if asset_type == "nps":
        by_class = _NPS_CLASS.get(str(item.get("asset_class") or "").upper())
        if by_class:
            return by_class
        # Themed, lifecycle, composite, tax saver, government and similar schemes: name rules.
        name = item.get("scheme_name")
        if "EQUITY" in _TOKEN.findall((name or "").upper()):
            return "equity"
        return "debt" if classify_by_name(name) == "debt" else "hybrid"
    if asset_type in ("fd", "rd", "pf"):
        return "debt"
    if asset_type == "gold":
        return "gold"
    if asset_type == "cash":
        return "cash"
    return "other"


def is_retirement(asset_type: str, item: Mapping[str, Any]) -> bool:
    """EPF, VPF, PPF and NPS Tier I. A missing NPS tier counts as Tier I; only Tier II is not."""
    if asset_type == "pf":
        return True
    if asset_type == "nps":
        return item.get("tier") != "II"
    return False


# --- Active holdings ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Holding:
    type: str
    type_label: str
    id: Any
    name: str
    value: Decimal
    cls: str
    retirement: bool
    item: Mapping[str, Any]


def _active_holdings(
    groups: Iterable[Mapping[str, Any]],
    *,
    stock_masters: Mapping[Any, Any] | None = None,
    bond_masters: Mapping[Any, Any] | None = None,
    mf_masters: Mapping[Any, Any] | None = None,
) -> list[_Holding]:
    out = []
    for group in groups:
        asset_type = group["type"]
        for item in group.get("items", []):
            if item.get("status") != "active":
                continue
            out.append(
                _Holding(
                    type=asset_type,
                    type_label=group.get("label", asset_type),
                    id=item.get("id"),
                    name=_item_name(item),
                    value=_dec(item.get("current_value")),
                    cls=classify_holding(
                        asset_type,
                        item,
                        stock_masters=stock_masters,
                        bond_masters=bond_masters,
                        mf_masters=mf_masters,
                    ),
                    retirement=is_retirement(asset_type, item),
                    item=item,
                )
            )
    return out


def _sum(holdings: Iterable[_Holding]) -> Decimal:
    return sum((h.value for h in holdings), _ZERO)


# --- 1. Allocation -----------------------------------------------------------------------------


def _allocation_view(holdings: list[_Holding]) -> dict[str, Any]:
    total = _sum(holdings)
    classes = []
    for cls in CLASSES:
        in_class = [h for h in holdings if h.cls == cls]
        value = _sum(in_class)
        if not value:
            continue
        types: dict[str, list[_Holding]] = {}
        for h in in_class:
            types.setdefault(h.type, []).append(h)
        type_rows = []
        for asset_type, members in types.items():
            ordered = sorted(members, key=lambda h: (-h.value, str(h.id)))
            type_value = _sum(members)
            type_rows.append(
                {
                    "type": asset_type,
                    "label": members[0].type_label,
                    "value": _q(type_value),
                    "percent": _pct(type_value, total),
                    "holdings": [
                        {
                            "id": h.id,
                            "name": h.name,
                            "value": _q(h.value),
                            "percent": _pct(h.value, total),
                        }
                        for h in ordered
                    ],
                }
            )
        type_rows.sort(key=lambda t: (-t["value"], t["type"]))
        classes.append(
            {
                "class": cls,
                "label": CLASS_LABELS[cls],
                "value": _q(value),
                "percent": _pct(value, total),
                "types": type_rows,
            }
        )
    return {"total": _q(total), "classes": classes}


def allocation(
    groups: Sequence[Mapping[str, Any]],
    *,
    stock_masters: Mapping[Any, Any] | None = None,
    bond_masters: Mapping[Any, Any] | None = None,
    mf_masters: Mapping[Any, Any] | None = None,
) -> dict[str, Any]:
    """Allocation by asset class with the drill-down class -> asset type -> holdings.

    Returns {"including_retirement": view, "excluding_retirement": view, "retirement_value",
    "retirement_percent"}; a view is {"total", "classes": [{class, label, value, percent,
    types: [{type, label, value, percent, holdings: [{id, name, value, percent}]}]}]}. Percents
    are of that view's total; classes with no value are left out.
    """
    holdings = _active_holdings(
        groups, stock_masters=stock_masters, bond_masters=bond_masters, mf_masters=mf_masters
    )
    retirement = _sum(h for h in holdings if h.retirement)
    return {
        "including_retirement": _allocation_view(holdings),
        "excluding_retirement": _allocation_view([h for h in holdings if not h.retirement]),
        "retirement_value": _q(retirement),
        "retirement_percent": _pct(retirement, _sum(holdings)),
    }


# --- 2. Concentration --------------------------------------------------------------------------


class Bank(NamedTuple):
    key: str  # "issuer:<survivor id>" or "name:<trimmed lower-case entered name>"
    name: str
    issuer_id: int | None  # the surviving issuer's id, None for a manually entered bank


def resolve_issuer_id(issuer_id: int | None, issuer_masters: Mapping[Any, Any]) -> int | None:
    """Follow merged_into_id to the surviving issuer; None when the issuer isn't in the lookup.

    A chain (A -> B -> C) ends at C. If the data loops, the smallest id in the loop wins, so every
    member of the loop resolves to the same survivor. A merged_into_id missing from the lookup
    stops the walk at the last known issuer.
    """
    path: list[Any] = []
    position: dict[Any, int] = {}
    current = issuer_id
    while current is not None and current in issuer_masters:
        if current in position:
            return min(path[position[current]:])
        position[current] = len(path)
        path.append(current)
        current = _field(issuer_masters[current], "merged_into_id")
    return path[-1] if path else None


def _match_issuer_by_name(name: Any, issuer_masters: Mapping[Any, Any]) -> int | None:
    """The surviving issuer whose name, else short name, equals `name` (trimmed, case-insensitive).

    Merged issuers match too and resolve to their survivor. The full name is tried before the
    short name. A name that reaches more than one survivor in the same tier is ambiguous: no match.
    """
    key = _norm(name)
    if not key:
        return None
    for column in ("name", "short_name"):
        survivors = {
            resolve_issuer_id(issuer_id, issuer_masters)
            for issuer_id, master in issuer_masters.items()
            if _norm(_field(master, column)) == key
        }
        if survivors:
            return survivors.pop() if len(survivors) == 1 else None
    return None


def resolve_bank(item: Mapping[str, Any], issuer_masters: Mapping[Any, Any] | None = None) -> Bank:
    """The bank an FD or RD rolls up to: the merged-into survivor when it has an issuer_id; else
    the issuer whose name or short name equals the entered bank name (trimmed, case-insensitive,
    following merges); else the entered name itself, which groups case-insensitively.
    """
    issuer_masters = issuer_masters or {}
    survivor = resolve_issuer_id(item.get("issuer_id"), issuer_masters)
    if survivor is None:
        survivor = _match_issuer_by_name(item.get("bank"), issuer_masters)
    if survivor is not None:
        master = issuer_masters[survivor]
        name = _clean(_field(master, "short_name") or _field(master, "name") or item.get("bank"))
        return Bank(f"issuer:{survivor}", name or "Unknown bank", survivor)
    name = _clean(item.get("bank"))
    return Bank(f"name:{_norm(name)}", name or "Unknown bank", None)


def _rollup(
    key: str, label: str, entries: Iterable[tuple[str, str, Decimal, bool]]
) -> dict[str, Any]:
    """Bars from (bar key, bar label, value, passive) entries; percents of the group total."""
    bars: dict[str, dict[str, Any]] = {}
    for bar_key, bar_label, value, passive in entries:
        bar = bars.setdefault(
            bar_key, {"key": bar_key, "label": bar_label, "_value": _ZERO, "passive": passive}
        )
        bar["_value"] += value
    total = sum((b["_value"] for b in bars.values()), _ZERO)
    rows = [
        {
            "key": b["key"],
            "label": b["label"],
            "value": _q(b["_value"]),
            "percent": _pct(b["_value"], total),
            "passive": b["passive"],
            "_raw": b["_value"],
        }
        for b in bars.values()
    ]
    rows.sort(key=lambda r: (-r["_raw"], r["label"].casefold(), r["key"]))
    return {"key": key, "label": label, "total": _q(total), "bars": rows}


def concentration(
    groups: Sequence[Mapping[str, Any]],
    *,
    stock_masters: Mapping[Any, Any] | None = None,
    bond_masters: Mapping[Any, Any] | None = None,
    mf_masters: Mapping[Any, Any] | None = None,
    issuer_masters: Mapping[Any, Any] | None = None,
) -> dict[str, Any]:
    """Top holdings, issuer-group rollups and concentration flags.

    Returns {"total", "top_holdings": [{type, id, name, value, percent}] (10, by value then type
    then id), "rollups": [{key, label, total, bars: [{key, label, value, percent, passive}]}]
    for stock company, MF AMC, FD/RD bank, bond issuer and NPS PFM (percent of that group's own
    total; ETF bars are passive), "flags": [{kind, key, label, value, percent, threshold}]}.
    Flags: a non-ETF stock company strictly over 10% of the equity class total (retirement money
    included), and an AMC strictly over 30% of the MF total. Passive funds and ETFs never get
    the single-stock flag.
    """
    stock_masters = stock_masters or {}
    bond_masters = bond_masters or {}
    mf_masters = mf_masters or {}
    issuer_masters = issuer_masters or {}
    holdings = _active_holdings(
        groups, stock_masters=stock_masters, bond_masters=bond_masters, mf_masters=mf_masters
    )
    total = _sum(holdings)

    ranked = sorted(holdings, key=lambda h: (-h.value, h.type, str(h.id)))[:TOP_HOLDINGS]
    top = [
        {
            "type": h.type,
            "id": h.id,
            "name": h.name,
            "value": _q(h.value),
            "percent": _pct(h.value, total),
        }
        for h in ranked
    ]

    stocks, amcs, banks, issuers, pfms = [], [], [], [], []
    for h in holdings:
        item = h.item
        if h.type == "stock":
            master = stock_masters.get(item.get("master_id"))
            key = f"master:{item['master_id']}" if item.get("master_id") is not None else None
            name = _clean(_field(master, "name") or item.get("name"))
            stocks.append(
                (key or f"name:{_norm(name)}", name, h.value, _field(master, "kind") == "etf")
            )
        elif h.type == "mf":
            amc = _clean(_field(mf_masters.get(item.get("scheme_code")), "amc"))
            amcs.append((_norm(amc) or "unknown", amc or "Unknown AMC", h.value, False))
        elif h.type in ("fd", "rd"):
            bank = resolve_bank(item, issuer_masters)
            banks.append((bank.key, bank.name, h.value, False))
        elif h.type == "bond":
            master = bond_masters.get(item.get("master_id"))
            issuer = _clean(_field(master, "issuer") or item.get("issuer"))
            issuers.append((_norm(issuer) or "unknown", issuer or "Unknown issuer", h.value, False))
        elif h.type == "nps":
            pfm = _clean(item.get("pfm_name"))
            pfms.append((_norm(pfm) or "unknown", pfm or "Unknown PFM", h.value, False))

    rollups = [
        _rollup("stock", "Stocks by company", stocks),
        _rollup("mf_amc", "Mutual funds by AMC", amcs),
        _rollup("bank", "FD and RD by bank", banks),
        _rollup("bond_issuer", "Bonds by issuer", issuers),
        _rollup("nps_pfm", "NPS by pension fund manager", pfms),
    ]

    flags = []
    equity_total = _sum(h for h in holdings if h.cls == "equity")
    for bar in rollups[0]["bars"]:
        if not bar["passive"] and equity_total and bar["_raw"] * _HUNDRED > equity_total * STOCK_FLAG_PCT:
            flags.append(_flag("single_stock", bar, equity_total, STOCK_FLAG_PCT))
    mf_total = _sum(h for h in holdings if h.type == "mf")
    for bar in rollups[1]["bars"]:
        if mf_total and bar["_raw"] * _HUNDRED > mf_total * AMC_FLAG_PCT:
            flags.append(_flag("amc", bar, mf_total, AMC_FLAG_PCT))

    for rollup in rollups:
        for bar in rollup["bars"]:
            del bar["_raw"]
    return {"total": _q(total), "top_holdings": top, "rollups": rollups, "flags": flags}


def _flag(kind: str, bar: dict[str, Any], denominator: Decimal, threshold: Decimal) -> dict[str, Any]:
    return {
        "kind": kind,
        "key": bar["key"],
        "label": bar["label"],
        "value": bar["value"],
        "percent": _pct(bar["_raw"], denominator),
        "threshold": threshold,
    }


# --- 3. Liquidity ------------------------------------------------------------------------------


def _remaining_lots(transactions: Sequence[Mapping[str, Any]]) -> list[tuple[date, Decimal]]:
    """Purchase lots left after FIFO redemptions, oldest first. Same-day purchases go first."""
    rows = []
    for txn in transactions:
        when = _to_date(_field(txn, "txn_date"))
        kind = _field(txn, "kind")
        if when is None or kind not in ("purchase", "redemption"):
            continue
        rows.append((when, 0 if kind == "purchase" else 1, _dec(_field(txn, "units"))))
    rows.sort(key=lambda r: (r[0], r[1]))
    lots: deque[list[Any]] = deque()
    for when, order, units in rows:
        if order == 0:
            lots.append([when, units])
            continue
        while units > 0 and lots:
            take = min(units, lots[0][1])
            lots[0][1] -= take
            units -= take
            if lots[0][1] <= 0:
                lots.popleft()
    return [(d, u) for d, u in lots if u > 0]


def _is_locked(purchased: date, today: date) -> bool:
    """Locked until three years after purchase; a unit bought exactly 3 years ago is free."""
    return today < purchased + relativedelta(years=ELSS_LOCK_YEARS)


def elss_split(
    value: Decimal,
    purchase_date: Any,
    transactions: Sequence[Mapping[str, Any]] | None,
    today: date,
) -> tuple[Decimal, Decimal]:
    """(locked, free) parts of an ELSS fund's value.

    With transactions: lots, FIFO redemptions, then the value split by remaining units still
    inside the lock-in (the locked part is rounded to 2 dp, the free part is the rest, so the two
    always add back to `value`). Without usable lots, the whole fund follows its purchase date;
    with no date at all it counts as locked.
    """
    lots = _remaining_lots(transactions or [])
    units = sum((u for _, u in lots), _ZERO)
    if units > 0:
        locked_units = sum((u for d, u in lots if _is_locked(d, today)), _ZERO)
        locked = _q(value * locked_units / units)
        return locked, value - locked
    bought = _to_date(purchase_date)
    if bought is None or _is_locked(bought, today):
        return value, _ZERO
    return _ZERO, value


def _bucket(asset_type: str, item: Mapping[str, Any]) -> str | None:
    """The liquidity bucket of a holding; None for ELSS funds, which are split per lot."""
    if asset_type == "cash":
        return "instant"
    if asset_type in ("fd", "rd"):
        return "breakable"
    if asset_type == "bond":
        return "illiquid"
    if asset_type == "pf":
        return "locked"
    if asset_type == "nps":
        return "days" if item.get("tier") == "II" else "locked"
    if asset_type == "gold":
        return "days" if item.get("form") == "digital" else "illiquid"
    if asset_type in ("stock", "mf"):
        return "days"
    return "not_classified"


def liquidity(
    groups: Sequence[Mapping[str, Any]],
    *,
    today: date,
    mf_masters: Mapping[Any, Any] | None = None,
    mf_transactions: Mapping[Any, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """The liquidity ladder: {"total", "buckets": [{key, label, amount, percent}]}.

    Buckets, in order: instant (cash), days (MF other than ELSS, stocks, ETFs, digital gold, NPS
    Tier II), breakable (FD, RD), illiquid (bonds, physical gold and silver), locked (EPF, VPF,
    PPF, NPS Tier I, ELSS inside its 3-year lock), not_classified (Other). Every bucket is always
    listed; amounts add up to the active total. Retirement money is included.
    """
    mf_masters = mf_masters or {}
    mf_transactions = mf_transactions or {}
    amounts = {key: _ZERO for key, _ in BUCKETS}
    for group in groups:
        asset_type = group["type"]
        for item in group.get("items", []):
            if item.get("status") != "active":
                continue
            value = _dec(item.get("current_value"))
            bucket = _bucket(asset_type, item)
            if asset_type == "mf" and is_elss(item, mf_masters.get(item.get("scheme_code"))):
                locked, free = elss_split(
                    value, item.get("purchase_date"), mf_transactions.get(item.get("id")), today
                )
                amounts["locked"] += locked
                amounts["days"] += free
            else:
                amounts[bucket] += value
    total = sum(amounts.values(), _ZERO)
    return {
        "total": _q(total),
        "buckets": [
            {
                "key": key,
                "label": label,
                "amount": _q(amounts[key]),
                "percent": _pct(amounts[key], total),
            }
            for key, label in BUCKETS
        ],
    }


# --- 4. Coming up (maturities) -----------------------------------------------------------------


def _valued_obj(
    item: Mapping[str, Any],
    *,
    decimals: Sequence[str] = (),
    dates: Sequence[str] = (),
    ints: Sequence[str] = (),
) -> SimpleNamespace:
    """The attribute object the valuation functions read, built from a JSON item: dates parsed
    from ISO strings, floats to Decimal (through str), a missing optional value left as None."""
    data = dict(item)
    for key in decimals:
        data[key] = _dec(item[key]) if item.get(key) is not None else None
    for key in dates:
        data[key] = _to_date(item.get(key))
    for key in ints:
        data[key] = int(item.get(key) or 0)
    return SimpleNamespace(**data)


_FD_FIELDS = {
    "decimals": ("principal", "rate"),
    "dates": ("start_date",),
    "ints": ("tenure_years", "tenure_months", "tenure_days"),
}
_RD_FIELDS = {**_FD_FIELDS, "decimals": ("monthly_instalment", "rate")}
_BOND_FIELDS = {
    "decimals": ("invested_amount", "ytm"),
    "dates": ("purchase_date", "maturity_date"),
}
_PF_FIELDS = {
    "decimals": ("balance", "interest_rate", "contributed"),
    "dates": ("balance_date", "opened_on"),
}


def _maturity_amount(
    asset_type: str, item: Mapping[str, Any], maturity: date, bond_masters: Mapping[Any, Any]
) -> tuple[Decimal, Any, bool]:
    """(amount at maturity, rate, approximate) for an active FD, RD, bond or PPF."""
    if asset_type == "fd":
        rate = item.get("rate")
        if item.get("payout_type") == "payout":
            return _dec(item.get("principal")), rate, False
        value = valuation.value_fd(_valued_obj(item, **_FD_FIELDS), maturity)
        return value["current_value"], rate, False
    if asset_type == "rd":
        # Valued on its maturity date every instalment has been paid, so this is the full payout.
        value = valuation.value_rd(_valued_obj(item, **_RD_FIELDS), maturity)
        return value["current_value"], item.get("rate"), True
    if asset_type == "bond":
        master = bond_masters.get(item.get("master_id"))
        if item.get("bond_type") == "sgb" or _field(master, "bond_type") == "sgb":
            # An SGB redeems at the gold price then: today's value is the best estimate.
            return _dec(item.get("current_value")), item.get("ytm"), True
        if item.get("face_value") is not None:
            return _dec(item["face_value"]) * _dec(item.get("quantity")), item.get("ytm"), False
        # A bond saved before face value existed: its invested amount grown at the yield.
        value = valuation.value_bond(_valued_obj(item, **_BOND_FIELDS), maturity)
        return value["current_value"], item.get("ytm"), True
    # PPF: the balance plus interest to maturity; later contributions are unknown.
    value = valuation.value_pf(_valued_obj(item, **_PF_FIELDS), maturity)
    return value["current_value"], item.get("interest_rate"), True


def _window(rows: list[dict[str, Any]], until: date) -> dict[str, Any]:
    chosen = [r for r in rows if r["maturity_date"] <= until]
    return {
        "until": until,
        "total": _q(sum((r["amount"] for r in chosen), _ZERO)),
        "rows": chosen,
    }


def coming_up(
    groups: Sequence[Mapping[str, Any]],
    today: date,
    *,
    bond_masters: Mapping[Any, Any] | None = None,
) -> dict[str, Any]:
    """Maturities of active FDs, RDs, bonds and PPFs falling strictly after `today`.

    Returns {"next_90_days": window, "next_12_months": window, "already_matured": {"count",
    "rows": [{type, id, name, maturity_date}]}}; a window is {"until", "total", "rows"} and its
    rows are {type, id, name, maturity_date, amount, rate, days_left, approximate}, sorted by
    date, type, id. next_90_days runs to today + 90 days and next_12_months to today + 1 calendar
    year, both inclusive; the 12-month list includes the 90-day rows.

    Amount: cumulative FD, its value on maturity; payout FD, its principal; RD, its value on
    maturity with every instalment paid (approximate); bond, face value x quantity (an SGB, its
    current value, since it redeems at the gold price; a bond with no face value, its invested
    amount grown at the yield: both approximate); PPF, balance plus interest to maturity
    (approximate: later contributions are unknown). Perpetual bonds have no date and are skipped.
    Matured holdings are listed separately and never counted in a total.
    """
    bond_masters = bond_masters or {}
    rows: list[dict[str, Any]] = []
    matured: list[dict[str, Any]] = []
    for group in groups:
        asset_type = group["type"]
        for item in group.get("items", []):
            maturity = _to_date(item.get("maturity_date"))
            if item.get("status") == "matured":
                matured.append(
                    {
                        "type": asset_type,
                        "id": item.get("id"),
                        "name": _item_name(item),
                        "maturity_date": maturity,
                    }
                )
                continue
            if (
                item.get("status") != "active"
                or asset_type not in ("fd", "rd", "bond", "pf")
                or maturity is None
                or maturity <= today
            ):
                continue
            if asset_type == "pf" and item.get("kind") != "ppf":
                continue
            amount, rate, approximate = _maturity_amount(asset_type, item, maturity, bond_masters)
            rows.append(
                {
                    "type": asset_type,
                    "id": item.get("id"),
                    "name": _item_name(item),
                    "maturity_date": maturity,
                    "amount": _q(amount),
                    "rate": _q(_dec(rate)),
                    "days_left": (maturity - today).days,
                    "approximate": approximate,
                }
            )
    rows.sort(key=lambda r: (r["maturity_date"], r["type"], str(r["id"])))
    matured.sort(key=lambda r: (r["maturity_date"] or date.max, r["type"], str(r["id"])))
    return {
        "next_90_days": _window(rows, today + timedelta(days=COMING_UP_DAYS)),
        "next_12_months": _window(rows, today + relativedelta(years=1)),
        "already_matured": {"count": len(matured), "rows": matured},
    }


# --- 5. Bank safety (DICGC) --------------------------------------------------------------------

_COOPERATIVE = frozenset({"state_coop", "district_coop", "urban_coop"})
_NOT_INSURED_CATEGORIES = frozenset({"nbfc", "hfc"})


def _safety_status(master: Any) -> str:
    """insured | not_insured | sovereign | unknown, from the surviving issuer's category and flag.

    The master stores dicgc_insured as true when matched against the DICGC list and NULL
    otherwise (never false), so NULL on a bank means unknown, while NBFCs and HFCs, which can't
    be DICGC-insured, are not_insured whatever the flag says.
    """
    if master is None:
        return "unknown"
    category = _field(master, "category")
    if category == "post_office":
        return "sovereign"
    if category in _NOT_INSURED_CATEGORIES:
        return "not_insured"
    flag = _field(master, "dicgc_insured")
    if flag is None:
        return "unknown"
    return "insured" if flag else "not_insured"


def _badges(master: Any, status: str) -> list[str]:
    category = _field(master, "category")
    badges = []
    if status == "not_insured":
        badges.append("not_dicgc")
    if category in _COOPERATIVE:
        badges.append("cooperative")
    if category == "small_finance":
        badges.append("small_finance")
    if category == "post_office":
        badges.append("post_office")
    return badges


def bank_safety(
    groups: Sequence[Mapping[str, Any]], issuer_masters: Mapping[Any, Any] | None = None
) -> dict[str, Any]:
    """Deposit insurance cover per bank, from active FDs and RDs rolled up with `resolve_bank`.

    Exposure per deposit: its current value (principal plus accrued interest); a payout FD,
    its principal only (the interest is paid out). Each bank row is rounded to 2 dp and the
    totals are sums of the rows, so the figures always reconcile.

    Status per bank, from the surviving issuer: "insured" (insured = min(total, 5,00,000),
    excess = the rest), "not_insured" (insured 0, excess = total), "sovereign" (Post Office:
    insured None, excess 0), "unknown" (flag NULL or no linked issuer: insured and excess None,
    never counted as uninsured). Badges: not_dicgc, cooperative, small_finance, post_office.

    Returns {"limit", "total_deposits", "insured", "uninsured_excess", "unknown_amount",
    "sovereign_amount", "banks": [{key, name, issuer_id, category, status, badges, total,
    insured, excess, holdings: [{type, id, name, label, rate, maturity_date, payout, amount}]}]}, banks sorted by excess then total,
    largest first. total_deposits = insured + uninsured_excess + unknown_amount +
    sovereign_amount.
    """
    issuer_masters = issuer_masters or {}
    banks: dict[str, dict[str, Any]] = {}
    for h in _active_holdings(groups):
        if h.type not in ("fd", "rd"):
            continue
        item = h.item
        bank = resolve_bank(item, issuer_masters)
        if h.type == "fd" and item.get("payout_type") == "payout":
            amount = _dec(item.get("principal"))
        else:
            amount = h.value
        entry = banks.setdefault(bank.key, {"bank": bank, "_total": _ZERO, "holdings": []})
        entry["_total"] += amount
        entry["holdings"].append(
            {
                "type": h.type,
                "id": h.id,
                "name": h.name,
                "label": item.get("label") or None,
                "rate": _q(_dec(item.get("rate"))) if item.get("rate") is not None else None,
                "maturity_date": _to_date(item.get("maturity_date")),
                "payout": h.type == "fd" and item.get("payout_type") == "payout",
                "amount": _q(amount),
            }
        )

    rows = []
    sums = {"insured": _ZERO, "excess": _ZERO, "unknown": _ZERO, "sovereign": _ZERO}
    for key, entry in banks.items():
        bank: Bank = entry["bank"]
        master = issuer_masters.get(bank.issuer_id) if bank.issuer_id is not None else None
        status = _safety_status(master)
        total = _q(entry["_total"])
        insured: Decimal | None
        excess: Decimal | None
        if status == "insured":
            insured = min(total, DICGC_LIMIT)
            excess = total - insured
        elif status == "not_insured":
            insured, excess = _ZERO, total
        elif status == "sovereign":
            insured, excess = None, _ZERO
            sums["sovereign"] += total
        else:
            insured, excess = None, None
            sums["unknown"] += total
        sums["insured"] += insured or _ZERO
        sums["excess"] += excess or _ZERO
        rows.append(
            {
                "key": key,
                "name": bank.name,
                "issuer_id": bank.issuer_id,
                "category": _field(master, "category"),
                "status": status,
                "badges": _badges(master, status),
                "total": total,
                "insured": insured.quantize(_CENT) if insured is not None else None,
                "excess": excess.quantize(_CENT) if excess is not None else None,
                "holdings": sorted(entry["holdings"], key=lambda x: (x["type"], str(x["id"]))),
            }
        )
    rows.sort(key=lambda r: (-(r["excess"] or _ZERO), -r["total"], r["name"].casefold(), r["key"]))
    total_deposits = sum((r["total"] for r in rows), _ZERO)
    return {
        "limit": DICGC_LIMIT,
        "total_deposits": total_deposits.quantize(_CENT),
        "insured": sums["insured"].quantize(_CENT),
        "uninsured_excess": sums["excess"].quantize(_CENT),
        "unknown_amount": sums["unknown"].quantize(_CENT),
        "sovereign_amount": sums["sovereign"].quantize(_CENT),
        "banks": rows,
    }


# --- 6. Data health ----------------------------------------------------------------------------

# Item fields that are None when the holding is valued at cost (no price, NAV or rate known).
_PRICE_FIELD = {"stock": "price", "mf": "nav", "nps": "nav", "gold": "rate_per_gram"}
# The date field behind the "latest ... date" lines.
_LATEST_FIELD = {
    "stock": ("stock_price", "price_time"),
    "mf": ("mf_nav", "nav_date"),
    "nps": ("nps_nav", "nav_date"),
    "gold": ("gold_rate", "rate_date"),
}
# Hand-entered balances that go out of date.
_BALANCE_DATE_FIELD = {"cash": "balance_date", "pf": "balance_date", "other": "value_date"}


def data_health(groups: Sequence[Mapping[str, Any]], today: date) -> dict[str, Any]:
    """Counts and lists of holdings that make the numbers less trustworthy.

    Returns {"at_cost", "stale_balances", "matured_open", "latest"}; each of the first three is
    {"count", "items": [{type, id, name, ...}]} in portfolio order.
      at_cost          active stocks, MFs, NPS and gold with no price, NAV or rate (valued at cost)
      stale_balances   active cash, EPF/PPF and Other whose balance or value date is more than 6
                       calendar months before `today` (exactly 6 months is not stale); items
                       carry "as_of"
      matured_open     holdings whose status is matured (items carry "maturity_date")
      latest           {"stock_price", "mf_nav", "nps_nav", "gold_rate"}: the newest such date
                       among held items, None when nothing has one
    """
    stale_before = today - relativedelta(months=STALE_MONTHS)
    at_cost: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    matured: list[dict[str, Any]] = []
    latest: dict[str, date | None] = {key: None for key, _ in _LATEST_FIELD.values()}
    for group in groups:
        asset_type = group["type"]
        for item in group.get("items", []):
            ref = {"type": asset_type, "id": item.get("id"), "name": _item_name(item)}
            if asset_type in _LATEST_FIELD:
                key, field = _LATEST_FIELD[asset_type]
                seen = _to_date(item.get(field))
                if seen is not None and (latest[key] is None or seen > latest[key]):
                    latest[key] = seen
            if item.get("status") == "matured":
                matured.append({**ref, "maturity_date": _to_date(item.get("maturity_date"))})
            if item.get("status") != "active":
                continue
            if asset_type in _PRICE_FIELD and item.get(_PRICE_FIELD[asset_type]) is None:
                at_cost.append(ref)
            if asset_type in _BALANCE_DATE_FIELD:
                as_of = _to_date(item.get(_BALANCE_DATE_FIELD[asset_type]))
                if as_of is not None and as_of < stale_before:
                    stale.append({**ref, "as_of": as_of})
    return {
        "at_cost": {"count": len(at_cost), "items": at_cost},
        "stale_balances": {"count": len(stale), "items": stale},
        "matured_open": {"count": len(matured), "items": matured},
        "latest": latest,
    }

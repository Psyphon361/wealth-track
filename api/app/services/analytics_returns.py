"""Returns (XIRR) overall, per asset class and per asset type. Pure maths over valued holdings
({type, items}) plus plain MF transactions; no DB. See SPEC §9 "Returns".

Cash flows per holding: negative = money in, positive = value today and any interest paid out
(payout FDs) on its payout date; gain includes that interest. Cash, EPF/VPF/PPF and NPS
have no stored flows, so they are excluded from XIRR and listed in `rates` instead.
"""

from collections import Counter
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Any, Callable, Iterable, Mapping, Sequence

from dateutil.relativedelta import relativedelta

from app.services import analytics, analytics_benchmark
from app.services.valuation import payout_fd_flows, xirr

ZERO = Decimal("0")
CENT = Decimal("0.01")
HUNDRED = Decimal(100)
BEST_WORST = 5
MIN_ANNUALISED_DAYS = 365
# Best / worst only rank holdings whose earliest flow is at least this many calendar months old.
MIN_RANKED_MONTHS = 6
NO_FLOW_TYPES = frozenset({"cash", "pf", "nps"})
EXCLUSION_REASONS = ("at_cost", "no_flows", "other_without_invested")
# Item fields that are None when the holding is valued at cost (same rule as data health).
PRICE_FIELD = {"stock": "price", "mf": "nav", "gold": "rate_per_gram"}

Flows = list[tuple[date, Decimal]]


def _q(value: Decimal) -> Decimal:
    return value.quantize(CENT)


def _dec(value: Any) -> Decimal:
    return Decimal(str(value)) if value is not None else ZERO


@dataclass(frozen=True)
class HoldingFlows:
    """Cash flows of one holding, or `reason` when it can't have any."""

    flows: Flows
    basis: str | None
    reason: str | None = None


def _excluded(reason: str) -> HoldingFlows:
    return HoldingFlows([], None, reason)


def _single(item: Mapping[str, Any], start_field: str, today: date) -> HoldingFlows:
    """-invested on the start date, +current value today."""
    start = analytics._to_date(item.get(start_field))
    invested = _dec(item.get("invested"))
    if start is None or start > today or invested <= 0:
        return _excluded("no_flows")
    return HoldingFlows(
        [(start, -invested), (today, _dec(item.get("current_value")))], "purchase_date"
    )


def _payout_fd_flows(item: Mapping[str, Any], today: date) -> HoldingFlows:
    """-principal on the start date, +each interest payout on its payout date (the schedule of
    `value_fd`), +principal (the current value) today; a payout falling today joins that last flow."""
    base = _single(item, "start_date", today)
    maturity = analytics._to_date(item.get("maturity_date"))
    if base.reason is not None or maturity is None:
        return base
    payouts = payout_fd_flows(
        analytics._to_date(item.get("start_date")),
        item["compounding"], item["rate"], item["principal"], today, maturity,
    )  # fmt: skip
    flows = list(base.flows[:-1])
    final = base.flows[-1][1]
    for day, amount in payouts:
        if day >= today:
            final += _q(_dec(amount))
        else:
            flows.append((day, _q(_dec(amount))))
    flows.append((today, final))
    return HoldingFlows(flows, base.basis)


def _rd_flows(item: Mapping[str, Any], today: date) -> HoldingFlows:
    """-instalment on each paid instalment date (as in `value_rd`), +current value today."""
    start = analytics._to_date(item.get("start_date"))
    maturity = analytics._to_date(item.get("maturity_date"))
    instalment = _dec(item.get("monthly_instalment"))
    if start is None or maturity is None or instalment <= 0:
        return _excluded("no_flows")
    flows: Flows = []
    k = 0
    while True:
        d = start + relativedelta(months=k)
        if d >= maturity or d > today:
            break
        flows.append((d, -instalment))
        k += 1
    if not flows:
        return _excluded("no_flows")
    flows.append((today, _dec(item.get("current_value"))))
    return HoldingFlows(flows, "instalments")


def _mf_flows(
    item: Mapping[str, Any],
    today: date,
    transactions: Sequence[Any],
    held_units: Decimal | None = None,
) -> HoldingFlows:
    """The stored transactions when their net units match the holding, else the invested amount
    on the purchase date (the same rule as `valuation.mf_xirr`). `held_units` replaces the
    holding's stored units in that test (a fully sold fund keeps its units but nets to 0)."""
    current = _dec(item.get("current_value"))
    if transactions:
        net = sum(
            (_dec(t.units) if t.kind == "purchase" else -_dec(t.units) for t in transactions),
            ZERO,
        )
        expected = _dec(item.get("units")) if held_units is None else held_units
        if abs(net - expected) <= Decimal("0.01"):
            flows = [
                (
                    analytics._to_date(t.txn_date),
                    -_dec(t.amount) if t.kind == "purchase" else _dec(t.amount),
                )
                for t in transactions
            ]
            flows.append((today, current))
            return HoldingFlows(flows, "transactions")
    return _single(item, "purchase_date", today)


def is_full_sale(exit_row: Any) -> bool:
    """True for the exit that closed a holding (its cost equals what was left; `prev_state.full`)."""
    return bool((exit_row.prev_state or {}).get("full"))


def original_cost(asset_type: str, item: Mapping[str, Any], exits: Sequence[Any] = ()) -> Decimal:
    """What the holding cost before any sale: the invested amount it has now plus the cost of its
    PARTIAL sales. A full sale keeps the holding's invested, so its cost is not added again."""
    base = item.get("invested_amount") if asset_type == "other" else item.get("invested")
    return _dec(base) + sum((_dec(e.cost) for e in exits if not is_full_sale(e)), ZERO)


def realised_gain(exits: Sequence[Any]) -> Decimal:
    """Money received from the sales less the cost of what was sold."""
    return sum((_dec(e.amount) - _dec(e.cost) for e in exits), ZERO)


def holding_flows(
    asset_type: str,
    item: Mapping[str, Any],
    today: date,
    transactions: Sequence[Any] = (),
    exits: Sequence[Any] = (),
) -> HoldingFlows:
    """Flows and basis of one valued holding (active, or fully sold with `exits`); `reason` is set
    when it is excluded. `exits` are its SALE exits: each adds its stored amount (already net of
    charges) on its date, and the first outflow becomes the original cost. A fully sold holding
    has no terminal value. A fund on the transactions basis already holds its sales."""
    sold = item.get("status") == "sold"
    if asset_type in NO_FLOW_TYPES:
        return _excluded("no_flows")
    field = PRICE_FIELD.get(asset_type)
    if not sold and field is not None and item.get(field) is None:
        return _excluded("at_cost")
    if asset_type == "other" and (
        item.get("invested_amount") is None or item.get("acquired_on") is None
    ):
        return _excluded("other_without_invested")
    held_units = None
    if exits:
        cost = original_cost(asset_type, item, exits)
        item = {**item, "invested_amount" if asset_type == "other" else "invested": cost}
        if asset_type == "mf":
            held_units = _dec(item.get("units")) - sum(
                (_dec(e.quantity) for e in exits if is_full_sale(e)), ZERO
            )
    if sold:
        item = {**item, "current_value": ZERO}
    built = _base_flows(asset_type, item, today, transactions, held_units)
    if built.reason is not None or not (sold or exits):
        return built
    flows = built.flows[:-1] if sold else list(built.flows)  # the last flow is the value today
    if built.basis != "transactions":
        flows += [(analytics._to_date(e.exit_date), _dec(e.amount)) for e in exits]
        flows.sort(key=lambda f: f[0])  # oldest first
    return HoldingFlows(flows, built.basis)


def _base_flows(
    asset_type: str,
    item: Mapping[str, Any],
    today: date,
    transactions: Sequence[Any],
    held_units: Decimal | None,
) -> HoldingFlows:
    if asset_type == "other":
        return _single({**item, "invested": item["invested_amount"]}, "acquired_on", today)
    if asset_type == "mf":
        return _mf_flows(item, today, transactions, held_units)
    if asset_type == "rd":
        return _rd_flows(item, today)
    start_field = {"fd": "start_date", "bond": "purchase_date", "stock": "buy_date"}.get(
        asset_type, "purchase_date"
    )
    if asset_type == "fd" and item.get("payout_type") == "payout":
        return _payout_fd_flows(item, today)
    return _single(item, start_field, today)


def return_of(
    flows: Flows, invested: Decimal, gain: Decimal, today: date
) -> tuple[Decimal | None, bool]:
    """(return %, annualised). XIRR when the earliest flow is at least 365 days old, else the
    absolute return gain / invested. The % is None when it can't be computed."""
    earliest = min(d for d, _ in flows)
    if (today - earliest).days < MIN_ANNUALISED_DAYS:
        return (_q(gain * HUNDRED / invested) if invested > 0 else None), False
    rate = xirr(flows)
    return (_q(rate * HUNDRED) if rate is not None else None), True


def _group(
    key: str, label: str, members: Sequence[dict[str, Any]], today: date
) -> dict[str, Any]:
    flows: Flows = [f for m in members for f in m["flows"]]
    invested = sum((m["invested"] for m in members), ZERO)
    current = sum((m["current"] for m in members), ZERO)
    gain = sum((m["gain"] for m in members), ZERO)
    pct, annualised = return_of(flows, invested, gain, today)
    bases = {m["basis"] for m in members}
    return {
        "key": key,
        "label": label,
        "holdings": len(members),
        "invested": _q(invested),
        "current": _q(current),
        "gain": _q(gain),
        "return_pct": pct,
        "annualised": annualised,
        "basis": bases.pop() if len(bases) == 1 else "mixed",
        "since": min(d for d, _ in flows),
    }


def yearly_return(flows: Flows, today: date) -> Decimal | None:
    """XIRR % of one holding for ranking, or None when its earliest flow is under
    MIN_RANKED_MONTHS old or the solver can't converge."""
    earliest = min(d for d, _ in flows)
    if earliest > today - relativedelta(months=MIN_RANKED_MONTHS):
        return None
    rate = xirr(flows)
    return _q(rate * HUNDRED) if rate is not None else None


def _ranked(holdings: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    ranked = [h for h in holdings if h.get("yearly") is not None]
    ordered = sorted(ranked, key=lambda h: (-h["yearly"], h["type"], h["id"]))

    def row(h: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": h["type"],
            "id": h["id"],
            "name": h["name"],
            "return_pct": h["yearly"],
            "gain": _q(h["gain"]),
        }

    best = ordered[:BEST_WORST]
    # The worst list never repeats a holding already in the best list.
    worst = [h for h in reversed(ordered) if h not in best][:BEST_WORST]
    return {"best": [row(h) for h in best], "worst": [row(h) for h in worst]}


def nav_cagr(
    start_nav: Decimal | None, latest_nav: Decimal | None, start: date, today: date
) -> Decimal | None:
    """Annual growth % of the scheme NAV since `start`; None without both NAVs or under a year."""
    days = (today - start).days
    if not start_nav or not latest_nav or start_nav <= 0 or days < MIN_ANNUALISED_DAYS:
        return None
    ratio = float(latest_nav / start_nav)
    return _q(Decimal(str(ratio ** (365 / days) - 1)) * HUNDRED)


def rates(
    groups: Sequence[Mapping[str, Any]],
    nps_start_navs: Mapping[Any, Decimal],
    today: date,
) -> list[dict[str, Any]]:
    """Reference rates for holdings without flows. EPF/VPF/PPF: the entered interest rate. NPS:
    scheme NAV CAGR since the start date (`nps_start_navs` is keyed by NPS holding id), else null."""
    out: list[dict[str, Any]] = []
    for group in groups:
        asset_type = group["type"]
        if asset_type not in ("pf", "nps"):
            continue
        for item in group.get("items", []):
            if item.get("status") != "active":
                continue
            base = {"type": asset_type, "id": item.get("id"), "name": analytics._item_name(item)}
            if asset_type == "pf":
                rate = item.get("interest_rate")
                out.append(
                    {**base, "basis": "interest_rate",
                     "rate_pct": _q(_dec(rate)) if rate is not None else None}
                )  # fmt: skip
            else:
                start = analytics._to_date(item.get("start_date"))
                latest = item.get("nav")
                cagr = (
                    nav_cagr(
                        nps_start_navs.get(item.get("id")),
                        _dec(latest) if latest is not None else None,
                        start,
                        today,
                    )
                    if start is not None
                    else None
                )
                out.append({**base, "basis": "nav_cagr", "rate_pct": cagr})
    return out


def returns(
    groups: Sequence[Mapping[str, Any]],
    today: date,
    *,
    stock_masters: Mapping[Any, Any] | None = None,
    bond_masters: Mapping[Any, Any] | None = None,
    mf_masters: Mapping[Any, Any] | None = None,
    mf_transactions: Mapping[Any, Sequence[Any]] | None = None,
    sale_exits: Mapping[tuple[str, Any], Sequence[Any]] | None = None,
    nps_start_navs: Mapping[Any, Decimal] | None = None,
    benchmark_loader: Callable[[date | None], analytics_benchmark.BenchmarkNavs | None]
    | None = None,
    cpi: Mapping[int, Decimal] | None = None,
) -> dict[str, Any]:
    """Overall, per-class and per-type returns, best/worst holdings, exclusions and rates.
    `benchmark_loader(earliest_flow_date)` fetches the index fund NAVs (it may skip those before
    the NAV on or before that date) and is only called when some holding has flows;
    `benchmark` is null without a loader, without flows, or when it returns None."""
    mf_transactions = mf_transactions or {}
    sale_exits = sale_exits or {}
    included: list[dict[str, Any]] = []
    excluded: Counter[str] = Counter()
    masters = {
        "stock_masters": stock_masters, "bond_masters": bond_masters, "mf_masters": mf_masters,
    }  # fmt: skip
    holdings = analytics._active_holdings(groups, **masters)
    # Fully sold holdings are counted here as realised results (the shared active filter leaves
    # them out of allocation and the other analytics). Matured ones stay out.
    sold_groups = [
        {
            **g,
            "items": [
                {**i, "status": "active"} for i in g.get("items", []) if i.get("status") == "sold"
            ],
        }
        for g in groups
    ]
    sold = [
        replace(h, item={**h.item, "status": "sold"})
        for h in analytics._active_holdings(sold_groups, **masters)
    ]
    for h in [*holdings, *sold]:
        is_sold = h.item.get("status") == "sold"
        exits = list(sale_exits.get((h.type, h.id), ()))
        if is_sold and not exits:
            continue
        txns = mf_transactions.get(h.id, ()) if h.type == "mf" else ()
        built = holding_flows(h.type, h.item, today, txns, exits)
        if built.reason is not None:
            if not is_sold:
                excluded[built.reason] += 1
            continue
        invested = original_cost(h.type, h.item, exits)
        if is_sold:
            current = ZERO
            unrealised = ZERO
        else:
            current = _dec(h.item.get("current_value"))
            item_gain = h.item.get("gain")
            unrealised = (
                _dec(item_gain)
                if item_gain is not None
                else current - _dec(
                    h.item.get("invested_amount" if h.type == "other" else "invested")
                )
            )
        gain = unrealised + realised_gain(exits)
        pct, annualised = return_of(built.flows, invested, gain, today)
        included.append(
            {
                "type": h.type, "type_label": h.type_label, "cls": h.cls, "id": h.id,
                "name": h.name, "flows": built.flows, "basis": built.basis,
                "invested": invested, "current": current, "gain": gain,
                "return_pct": pct, "annualised": annualised,
                "yearly": yearly_return(built.flows, today),
            }
        )  # fmt: skip

    by_type: list[dict[str, Any]] = []
    for group in groups:
        members = [m for m in included if m["type"] == group["type"]]
        if members:
            by_type.append(_group(group["type"], members[0]["type_label"], members, today))
    by_class = []
    for cls in analytics.CLASSES:
        members = [m for m in included if m["cls"] == cls]
        if members:
            by_class.append(_group(cls, analytics.CLASS_LABELS[cls], members, today))
    overall = _group("overall", "Portfolio", included, today) if included else None
    bench = None
    navs = None
    if benchmark_loader is not None and included:
        earliest = min((d for m in included for d, _ in m["flows"]), default=None)
        navs = benchmark_loader(earliest)
    if navs is not None and overall is not None:
        class_returns = {g["key"]: (g["return_pct"], g["annualised"]) for g in by_class}
        bench = analytics_benchmark.benchmark(
            {
                "equity": [f for m in included if m["cls"] == "equity" for f in m["flows"]]
            },
            [f for m in included for f in m["flows"]],
            class_returns,
            (overall["return_pct"], overall["annualised"]),
            overall["since"],
            navs,
            groups,
            today,
            cpi if cpi is not None else analytics_benchmark.load_cpi(),
        )
    return {
        "as_of": today,
        "overall": overall,
        "benchmark": bench,
        "by_class": by_class,
        "by_type": by_type,
        **_ranked(included),
        "rates": rates(groups, nps_start_navs or {}, today),
        "excluded": {reason: excluded[reason] for reason in EXCLUSION_REASONS},
    }

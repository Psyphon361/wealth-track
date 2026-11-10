"""Unrealised gains: what each open holding's gain would be taxed as if it were closed in full on
`today` at its current value. Pure functions: no DB, the clock is a parameter. Informational
estimates, not tax advice.

Everything reuses the realised-side rules in services/capital_gains.py: `classify`, `lot_bucket`
(term, the 23 Jul 2024 cut-off, buckets), `fy_totals` (bucket totals) and `exemption_limit`.

Lots: a fund is the lots LEFT after its earlier redemptions (`fifo_leftover_lots`, the same FIFO
order as `exits.fifo_cost`); its current value is split over them by units, the last lot taking the
rounding remainder. When those units do not add up to the holding's units (within 0.01) the fund is
one lot at the holding's purchase date with its invested amount (flag `single_lot_fallback`).
Lot costs are reconciled to the invested amount exactly as a real full redemption does
(`reconcile_lot_costs`: scaled when the FIFO cost is off by more than 1.00, else the last lot takes
the remainder), so lots add up to the holding's own gain. A stock is one average-price lot
(flag `single_lot_average`); every other holding is one lot.

`long_term_on` is the first day on which a lot counts as long term (the day after buy date + N
months, month end clamped), using the rules in force today (24 months for debt funds, bonds' and
listed others' 12, other assets' 24). It is null when the lot is already long term, can never be
(crypto is flat; a debt fund bought on or after 1 Apr 2023 stays short) or has no purchase date.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.services import capital_gains as cg
from app.services.capital_gains import MfTxn, SaleInput, money

_ZERO = Decimal(0)
_UNITS_TOLERANCE = Decimal("0.01")
TURNING_DAYS = 90


@dataclass
class HoldingInput:
    asset_type: str  # stock | bond | mf | gold | other
    holding_id: int
    name: str
    quantity: Decimal | None
    cost: Decimal  # invested amount
    value: Decimal  # current value
    bought_on: date | None
    stock_kind: str | None = None
    mf_category: str | None = None
    amfi_category: str | None = None
    bond_type: str | None = None
    bond_has_master: bool = True
    other_category: str | None = None
    mf_txns: list[MfTxn] = field(default_factory=list)
    estimated: bool = False  # the value is a model estimate, not a market price


def long_term_on(cls: str, bought_on: date | None, today: date) -> date | None:
    """First day the lot counts as long term, or None (see the module docstring)."""
    if cls == "crypto" or bought_on is None:
        return None
    if cls == "equity" or cls in ("bond", "listed_other"):
        months = 12
    elif cls == "debt_fund":
        if bought_on >= cg.DEBT_NEW_RULE_FROM:
            return None
        months = 24
    else:
        months = 24
    turns = cg.add_months(bought_on, months) + timedelta(days=1)
    return turns if turns > today else None


def _raw_lots(h: HoldingInput) -> tuple[list[dict[str, Any]], bool]:
    """The lots and whether a fund fell back to one lot although it has transactions."""
    cost = money(h.cost)
    value = money(h.value)
    single = [{"bought_on": h.bought_on, "quantity": h.quantity, "cost": cost, "value": value}]
    if h.asset_type != "mf" or h.quantity is None:
        return single, False
    left = cg.fifo_leftover_lots(h.mf_txns)
    total_units = sum((u for _, u, _ in left), _ZERO)
    if not left or total_units <= 0 or abs(total_units - h.quantity) > _UNITS_TOLERANCE:
        return single, bool(h.mf_txns)
    # Lot costs add up to the invested amount, like the realised side of a full redemption.
    reconciled = cg.reconcile_lot_costs(left, cost, h.quantity)
    if reconciled is None:
        return single, True
    costs, scaled = reconciled
    shares = cg.split_proceeds(value, [u for _, u, _ in left], scaled)
    lots: list[dict[str, Any]] = []
    for i, (bought, units, _) in enumerate(left):
        share = shares[i]
        lots.append(
            {
                "bought_on": bought,
                "quantity": units.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP),
                "cost": costs[i],
                "value": share,
            }
        )
    return lots, False


def build_holding(h: HoldingInput, today: date) -> dict[str, Any]:
    """One holding as the endpoint's holding dict: classified, split into lots and bucketed as if
    closed in full on `today`."""
    sale = SaleInput(
        exit_id=None,
        asset_type=h.asset_type,
        holding_id=h.holding_id,
        name=h.name,
        sold_on=today,
        quantity=h.quantity,
        proceeds=h.value,
        cost=h.cost,
        bought_on=h.bought_on,
        stock_kind=h.stock_kind,
        mf_category=h.mf_category,
        amfi_category=h.amfi_category,
        bond_type=h.bond_type,
        bond_has_master=h.bond_has_master,
        other_category=h.other_category,
    )
    cls, flags = cg.classify(sale)
    lots: list[dict[str, Any]] = []
    raw_lots, fallback = _raw_lots(h)
    if fallback:
        flags.append("single_lot_fallback")
    for raw in raw_lots:
        bought = raw["bought_on"]
        bucket, term, lot_flags = cg.lot_bucket(cls, bought, today)
        for f in lot_flags:
            if f not in flags:
                flags.append(f)
        turns = long_term_on(cls, bought, today)
        after = None
        if turns is not None:
            after = cg.lot_bucket(cls, bought, turns)[0]
        lots.append(
            {
                "bought_on": bought,
                "quantity": raw["quantity"],
                "cost": raw["cost"],
                "value": raw["value"],
                "gain": raw["value"] - raw["cost"],
                "days_held": (today - bought).days if bought else None,
                "term": term,
                "long_term_on": turns,
                "days_to_long_term": (turns - today).days if turns else None,
                "bucket": bucket,
                "bucket_after": after,
            }
        )
    if h.estimated:
        flags.append("estimated")
    if h.asset_type == "stock":
        flags.append("single_lot_average")
    cost = money(h.cost)
    value = money(h.value)
    return {
        "asset_type": h.asset_type,
        "holding_id": h.holding_id,
        "name": h.name,
        "cost": cost,
        "value": value,
        "gain": value - cost,
        "class": cls,
        "flags": flags,
        "lots": lots,
    }


def exemption_used(realised_buckets: list[dict[str, Any]]) -> Decimal:
    """Realised equity long-term net after set-off this year (buckets of the capital-gains
    response), each bucket floored at 0."""
    used = _ZERO
    for b in realised_buckets:
        if b["key"] in ("equity_lt", "equity_lt_old"):
            used += max(_ZERO, b["net"] - b["set_off"])
    return used


def _lot_ref(holding: dict[str, Any], lot: dict[str, Any]) -> dict[str, Any]:
    return {
        "asset_type": holding["asset_type"],
        "holding_id": holding["holding_id"],
        "name": holding["name"],
        "bought_on": lot["bought_on"],
        "quantity": lot["quantity"],
        "gain": lot["gain"],
        "bucket": lot["bucket"],
    }


def build_report(
    holdings: list[dict[str, Any]],
    start_year: int,
    today: date,
    realised_buckets: list[dict[str, Any]],
) -> dict[str, Any]:
    """Summary, buckets and harvest block for built holdings. `start_year` only selects the
    exemption limit and the realised usage; the unrealised side is always as of `today`."""
    all_lots = [lot for h in holdings for lot in h["lots"]]
    totals = cg.fy_totals([{"lots": all_lots}], start_year)
    buckets = [
        {k: b[k] for k in ("key", "label", "term", "rate", "gains", "losses", "net")}
        for b in totals["buckets"]
    ]
    limit = cg.exemption_limit(start_year)
    used = exemption_used(realised_buckets)
    horizon = today + timedelta(days=TURNING_DAYS)
    turning: list[dict[str, Any]] = []
    losses: list[dict[str, Any]] = []
    equity_lt_gain = _ZERO
    for h in holdings:
        for lot in h["lots"]:
            turns = lot["long_term_on"]
            if turns is not None and turns <= horizon:
                turning.append(
                    {
                        **_lot_ref(h, lot),
                        "long_term_on": turns,
                        "days_to_long_term": lot["days_to_long_term"],
                        "bucket_after": lot["bucket_after"],
                    }
                )
            if lot["bucket"] in ("equity_lt", "equity_lt_old") and lot["gain"] > 0:
                equity_lt_gain += lot["gain"]
            if lot["gain"] < 0 and lot["bucket"] not in (None, "crypto"):
                losses.append({**_lot_ref(h, lot), "term": lot["term"]})
    turning.sort(key=lambda t: (t["long_term_on"], t["holding_id"]))
    losses.sort(key=lambda t: (t["gain"], t["holding_id"]))
    summary = totals["summary"]
    return {
        "summary": {
            "total_gain": sum((lot["gain"] for lot in all_lots), _ZERO),
            "short_term_net": summary["short_term_net"],
            "long_term_net": summary["long_term_net"],
            "uncounted_lots": summary["excluded_lots"],
        },
        "buckets": buckets,
        "harvest": {
            "exemption_limit": limit,
            "exemption_used": used,
            "exemption_room": max(_ZERO, limit - used),
            "unrealised_equity_lt_gain": equity_lt_gain,
            "turning_long_term": turning,
            "loss_lots": losses,
        },
    }

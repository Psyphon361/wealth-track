"""Capital gains per Indian financial year, from the sales recorded in holding_exits. Pure
functions: no DB, the clock is a parameter. An estimate for tax filing help, not tax advice.

Classes (from the holding and its master): equity (listed stocks, equity/ELSS/equity-like hybrid
funds), debt_fund (debt funds, gilt/bond/liquid ETFs), bond (listed bonds, SGBs sold on the
exchange), listed_other (gold/silver ETFs and similar), other (unlisted fund of funds on gold or
silver, physical/digital gold, Other holdings), crypto. Classification that rests on a guess (an
ETF or fund judged by its name, a bond with no master, an unknown hybrid) carries the flag
`guessed_class`; multi-asset funds are class `other` with the flag `multi_asset`.

Lots: a sale of a stock, bond, gold or Other holding is one lot. A fund sale is split by FIFO over
the fund's transactions (same rule as exits.fifo_cost: oldest purchases first, earlier
redemptions consume first; purchases before redemptions on the same day, then id) into the lots
that redemption consumed. Proceeds (the exit amount, after charges) are split by units, the last
lot taking the rounding remainder. When the FIFO cost differs from the exit cost by more than 1.00
(an edited invested amount sold pro rata, or changed transactions) and the lots' units add up to
the sale quantity, the lots keep their dates and units and their costs are scaled to sum exactly
to the exit cost (cumulative rounding, proceeds split by units the same way); the total gain is
unchanged. When the redemption is not found, or those units do not add up, the sale is one lot at
the holding's purchase date with the exit cost.

Term: a lot is long term when it is sold AFTER buy date + N months (month-end clamped). Cut-off
date 23 Jul 2024 (sold on or after it, new rates):
- equity: N = 12. Short 20% (15% if sold before the cut-off), long 12.5% (10% before). Long
  lots bought before 1 Feb 2018 get the flag `grandfathering` (gain still on actual cost).
- debt_fund: bought on/after 1 Apr 2023 is always short, taxed at the slab. Bought earlier: sold
  on/after the cut-off N = 24, long 12.5% (other_lt), short slab; sold before it N = 36, short
  slab, long has no bucket (old indexed rules, flag `old_rules`).
- bond and listed_other: N = 12; short slab; long other_lt on/after the cut-off, else no bucket
  and `old_rules`.
- other: N = 24 on/after the cut-off (long other_lt), else N = 36 and long has no bucket and
  `old_rules`; short slab.
- crypto: flat 30% on each gain, term "flat", no loss set-off either way. It needs no buy date.
- Any other lot without a purchase date: no bucket, flag `no_purchase_date`.
Lots without a bucket are reported but not taxed (counted in summary.excluded_lots).

Financial year totals: per bucket gains (sum of positive lot gains), losses (sum of negative
ones, as positive numbers) and net. A bucket with a negative net is set off against buckets with
a positive net. Short-term losses (equity_st, equity_st_old, slab) go to slab, equity_st,
equity_st_old, other_lt, equity_lt, equity_lt_old in that order; long-term losses (other_lt,
equity_lt, equity_lt_old) go only to other_lt, equity_lt, equity_lt_old in that order. Crypto
neither gives nor takes. Then the equity long-term exemption (Rs 1,25,000 from FY 2024-25, else
Rs 1,00,000) reduces equity_lt first, then equity_lt_old. Taxable = net - set_off - exemption
for a positive bucket; tax = taxable x rate (slab: no rate, no tax). Crypto taxable is its
gains. Losses left after set-off are reported as unused (no carry forward is modelled).
"""

from calendar import monthrange
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.services import bond_schedule
from app.services.analytics import _field, _to_date
from app.services.analytics_tax import current_fy_start_year, fy_label

_ZERO = Decimal(0)
_CENT = Decimal("0.01")
CUTOFF = date(2024, 7, 23)
DEBT_NEW_RULE_FROM = date(2023, 4, 1)
GRANDFATHER_BEFORE = date(2018, 2, 1)
FIFO_TOLERANCE = Decimal("1.00")
EXEMPTION_NEW = Decimal(125000)
EXEMPTION_OLD = Decimal(100000)
EXEMPTION_NEW_FROM_FY = 2024

BUCKET_ORDER = (
    "equity_st",
    "equity_st_old",
    "equity_lt",
    "equity_lt_old",
    "other_lt",
    "slab",
    "crypto",
)
BUCKET_LABELS = {
    "equity_st": "Equity, Short Term",
    "equity_st_old": "Equity, Short Term (Before 23 Jul 2024)",
    "equity_lt": "Equity, Long Term",
    "equity_lt_old": "Equity, Long Term (Before 23 Jul 2024)",
    "other_lt": "Other Assets, Long Term",
    "slab": "Taxed At Your Slab",
    "crypto": "Crypto",
}
BUCKET_TERMS = {
    "equity_st": "short",
    "equity_st_old": "short",
    "equity_lt": "long",
    "equity_lt_old": "long",
    "other_lt": "long",
    "slab": "short",
    "crypto": "flat",
}
BUCKET_RATES: dict[str, Decimal | None] = {
    "equity_st": Decimal(20),
    "equity_st_old": Decimal(15),
    "equity_lt": Decimal("12.5"),
    "equity_lt_old": Decimal(10),
    "other_lt": Decimal("12.5"),
    "slab": None,
    "crypto": Decimal(30),
}
_SHORT_LOSS_ORDER = ("slab", "equity_st", "equity_st_old")
_LONG_LOSS_ORDER = ("other_lt", "equity_lt", "equity_lt_old")
_SETOFF_TARGETS_SHORT = (
    "slab",
    "equity_st",
    "equity_st_old",
    "other_lt",
    "equity_lt",
    "equity_lt_old",
)
_SETOFF_TARGETS_LONG = ("other_lt", "equity_lt", "equity_lt_old")

_DEBT_WORDS = (
    "gilt",
    "bond",
    "sdl",
    "liquid",
    "debt",
    "g-sec",
    "gsec",
    "treasury",
    "money market",
    "ibx",
)
_EQUITY_HYBRIDS = (
    "arbitrage",
    "aggressive hybrid",
    "balanced advantage",
    "dynamic asset allocation",
    "equity savings",
)


def money(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)


def _dec(value: Any) -> Decimal:
    return Decimal(str(value)) if value is not None else _ZERO


# --- Inputs ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MfTxn:
    id: int
    txn_date: date
    kind: str  # purchase | redemption
    units: Decimal
    amount: Decimal


@dataclass
class SaleInput:
    exit_id: int | None  # None for a bond repayment computed from the holding
    asset_type: str  # stock | bond | mf | gold | other
    holding_id: int
    name: str
    sold_on: date
    quantity: Decimal | None
    proceeds: Decimal  # exit.amount, after charges
    cost: Decimal
    bought_on: date | None
    # classification info
    stock_kind: str | None = None  # stock_master.kind: stock | etf; None = no master
    mf_category: str | None = None  # mf_master category: equity, elss, debt, ...
    amfi_category: str | None = None
    bond_type: str | None = None
    bond_has_master: bool = True
    other_category: str | None = None
    # mutual funds
    mf_txns: Sequence[MfTxn] = field(default_factory=tuple)
    mf_transaction_id: int | None = None
    # where the sale comes from: a recorded Sell, or a bond repayment computed from the holding
    source: str = "sale"  # sale | maturity | planned_sale
    estimated: bool = False


# --- Dates -------------------------------------------------------------------------------------


def fy_start_year_of(d: date) -> int:
    return d.year if d.month >= 4 else d.year - 1


def add_months(d: date, months: int) -> date:
    """`d` plus whole months; the day is clamped to the end of a shorter month."""
    index = d.year * 12 + (d.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(d.day, monthrange(year, month)[1]))


def available_fys(
    today: date, exit_dates: Iterable[date] = (), repayment_dates: Iterable[date] = ()
) -> list[dict[str, Any]]:
    """The current financial year plus every one containing an exit date, or a bond repayment date
    on or before the end of the current financial year, newest first."""
    current = current_fy_start_year(today)
    years = {current} | {fy_start_year_of(d) for d in exit_dates}
    years |= {fy_start_year_of(d) for d in repayment_dates if fy_start_year_of(d) <= current}
    return [
        {"start_year": y, "label": fy_label(y), "is_current": y == current}
        for y in sorted(years, reverse=True)
    ]


# --- Classification ----------------------------------------------------------------------------


def _name_has(name: str | None, words: Sequence[str]) -> bool:
    low = (name or "").lower()
    return any(w in low for w in words)


def _guess_fund_class(name: str | None, gold_class: str) -> str:
    if _name_has(name, ("gold", "silver")):
        return gold_class
    if _name_has(name, _DEBT_WORDS):
        return "debt_fund"
    return "equity"


def classify(sale: SaleInput) -> tuple[str, list[str]]:
    """(class, flags) of a sale. Classes: equity, debt_fund, bond, listed_other, other, crypto."""
    kind = sale.asset_type
    if kind == "stock":
        if sale.stock_kind == "stock":
            return "equity", []
        cls = _guess_fund_class(sale.name, "listed_other")
        return cls, ["guessed_class"]
    if kind == "mf":
        cat = (sale.mf_category or "").lower()
        if cat in ("equity", "elss"):
            return "equity", []
        if cat in ("debt", "liquid"):
            return "debt_fund", []
        if cat == "hybrid":
            amfi = (sale.amfi_category or "").lower()
            if "multi asset" in amfi:
                return "other", ["multi_asset"]
            if "conservative hybrid" in amfi:
                return "debt_fund", []
            if any(w in amfi for w in _EQUITY_HYBRIDS):
                return "equity", []
            return "equity", ["guessed_class"]
        return _guess_fund_class(sale.name, "other"), ["guessed_class"]
    if kind == "bond":
        return "bond", [] if sale.bond_has_master else ["guessed_class"]
    if kind == "gold":
        return "other", []
    if kind == "other":
        if "crypto" in (sale.other_category or "").lower():
            return "crypto", []
        return "other", []
    return "other", ["guessed_class"]


def lot_bucket(
    cls: str, bought_on: date | None, sold_on: date
) -> tuple[str | None, str | None, list[str]]:
    """(bucket or None, term short|long|flat|None, flags) of one lot."""
    if cls == "crypto":
        return "crypto", "flat", []
    if bought_on is None:
        return None, None, ["no_purchase_date"]
    new = sold_on >= CUTOFF
    flags: list[str] = []
    if cls == "equity":
        long_ = sold_on > add_months(bought_on, 12)
        if long_:
            if bought_on < GRANDFATHER_BEFORE:
                flags.append("grandfathering")
            return ("equity_lt" if new else "equity_lt_old"), "long", flags
        return ("equity_st" if new else "equity_st_old"), "short", flags
    if cls == "debt_fund":
        if bought_on >= DEBT_NEW_RULE_FROM:
            return "slab", "short", flags
        months = 24 if new else 36
    elif cls in ("bond", "listed_other"):
        months = 12
    else:
        months = 24 if new else 36
    if sold_on > add_months(bought_on, months):
        if new:
            return "other_lt", "long", flags
        return None, "long", ["old_rules"]
    return "slab", "short", flags


# --- Lots --------------------------------------------------------------------------------------


def _fifo_lots(txns: Sequence[MfTxn], redemption_id: int) -> list[tuple[date, Decimal, Decimal]] | None:
    """Lots (bought_on, units, cost) the redemption `redemption_id` consumed; None if absent."""
    ordered = sorted(txns, key=lambda t: (t.txn_date, t.kind != "purchase", t.id))
    lots: deque[list[Any]] = deque()  # [units, cost, date]
    for t in ordered:
        units = _dec(t.units)
        if t.kind == "purchase":
            lots.append([units, abs(_dec(t.amount)), t.txn_date])
            continue
        taken: list[tuple[date, Decimal, Decimal]] = []
        remaining = units
        while remaining > 0 and lots:
            lot = lots[0]
            if lot[0] <= remaining:
                remaining -= lot[0]
                taken.append((lot[2], lot[0], lot[1]))
                lots.popleft()
            else:
                part = lot[1] * remaining / lot[0]
                taken.append((lot[2], remaining, part))
                lot[1] -= part
                lot[0] -= remaining
                remaining = _ZERO
        if t.id == redemption_id:
            return taken
    return None


def fifo_leftover_lots(txns: Sequence[MfTxn]) -> list[tuple[date, Decimal, Decimal]]:
    """Lots (bought_on, units, cost) still held after every redemption in `txns`, oldest first.
    Same order and consumption as `_fifo_lots`; a redemption beyond the lots held is ignored."""
    ordered = sorted(txns, key=lambda t: (t.txn_date, t.kind != "purchase", t.id))
    lots: deque[list[Any]] = deque()  # [units, cost, date]
    for t in ordered:
        units = _dec(t.units)
        if t.kind == "purchase":
            lots.append([units, abs(_dec(t.amount)), t.txn_date])
            continue
        remaining = units
        while remaining > 0 and lots:
            lot = lots[0]
            if lot[0] <= remaining:
                remaining -= lot[0]
                lots.popleft()
            else:
                part = lot[1] * remaining / lot[0]
                lot[1] -= part
                lot[0] -= remaining
                remaining = _ZERO
    return [(lot[2], lot[0], lot[1]) for lot in lots]


def reconcile_lot_costs(
    taken: Sequence[tuple[date, Decimal, Decimal]], cost: Decimal, quantity: Decimal | None
) -> tuple[list[Decimal], bool] | None:
    """Lot costs that add up exactly to `cost` (the holding's or exit's invested amount, 2 dp).
    Returns (costs, scaled) or None when the lots cannot be trusted (no units, or the amount
    differs from the FIFO cost and the lots' units do not add up to `quantity`).
    Within FIFO_TOLERANCE of the FIFO cost the lots keep their FIFO costs and the last lot takes
    the remainder; further away (scaled=True) the costs are scaled by cumulative rounding."""
    total_units = sum((u for _, u, _ in taken), _ZERO)
    total_cost = sum((c for _, _, c in taken), _ZERO)
    if total_units <= 0:
        return None
    costs: list[Decimal] = []
    if abs(money(total_cost) - cost) > FIFO_TOLERANCE:
        if total_cost <= 0 or quantity is None or abs(total_units - quantity) > Decimal("0.01"):
            return None
        cum_fifo = _ZERO
        prev = _ZERO
        for i, (_, _, lot_cost) in enumerate(taken):
            cum_fifo += lot_cost
            cum = cost if i == len(taken) - 1 else money(cost * cum_fifo / total_cost)
            costs.append(cum - prev)
            prev = cum
        return costs, True
    given = _ZERO
    for i, (_, _, lot_cost) in enumerate(taken):
        out = cost - given if i == len(taken) - 1 else money(lot_cost)
        given += out
        costs.append(out)
    return costs, False


def split_proceeds(proceeds: Decimal, units: Sequence[Decimal], scaled: bool) -> list[Decimal]:
    """Split `proceeds` (2 dp) over lots by units; the shares add up exactly to `proceeds`.
    Scaled lot costs: cumulative rounding by units. Otherwise each lot is rounded on its own and
    the last lot takes the remainder. Shared by the realised and the unrealised side."""
    total_units = sum(units, _ZERO)
    shares: list[Decimal] = []
    given = _ZERO
    cum_units = _ZERO
    prev_proceeds = _ZERO
    for i, u in enumerate(units):
        last = i == len(units) - 1
        if scaled:
            cum_units += u
            cum_proceeds = proceeds if last else money(proceeds * cum_units / total_units)
            share = cum_proceeds - prev_proceeds
            prev_proceeds = cum_proceeds
        else:
            share = proceeds - given if last else money(proceeds * u / total_units)
            given += share
        shares.append(share)
    return shares


def split_lots(sale: SaleInput) -> list[dict[str, Any]]:
    """The lots of a sale as (bought_on, quantity, cost, proceeds) dicts."""
    proceeds = money(sale.proceeds)
    cost = money(sale.cost)
    single = [{"bought_on": sale.bought_on, "quantity": sale.quantity, "cost": cost, "proceeds": proceeds}]
    if sale.asset_type != "mf" or sale.mf_transaction_id is None or not sale.mf_txns:
        return single
    taken = _fifo_lots(sale.mf_txns, sale.mf_transaction_id)
    if not taken:
        return single
    # The exit cost may not be the FIFO cost (an edited invested amount, changed transactions):
    # keep the real lots (dates, units) and reconcile their costs to the exit cost.
    reconciled = reconcile_lot_costs(taken, cost, sale.quantity)
    if reconciled is None:
        return single
    costs, scaled = reconciled
    shares = split_proceeds(proceeds, [u for _, u, _ in taken], scaled)
    lots: list[dict[str, Any]] = []
    for i, (bought, units, _) in enumerate(taken):
        lots.append(
            {
                "bought_on": bought,
                "quantity": units.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP),
                "cost": costs[i],
                "proceeds": shares[i],
            }
        )
    return lots


def build_sale(sale: SaleInput) -> dict[str, Any]:
    """One sale as the endpoint's sale dict: classified, split into lots and bucketed."""
    cls, flags = classify(sale)
    out_lots: list[dict[str, Any]] = []
    for lot in split_lots(sale):
        bucket, term, lot_flags = lot_bucket(cls, lot["bought_on"], sale.sold_on)
        for f in lot_flags:
            if f not in flags:
                flags.append(f)
        bought = lot["bought_on"]
        out_lots.append(
            {
                "bought_on": bought,
                "quantity": lot["quantity"],
                "cost": lot["cost"],
                "proceeds": lot["proceeds"],
                "gain": lot["proceeds"] - lot["cost"],
                "days_held": (sale.sold_on - bought).days if bought else None,
                "term": term,
                "bucket": bucket,
            }
        )
    if sale.estimated and "estimated" not in flags:
        flags.append("estimated")
    return {
        "exit_id": sale.exit_id,
        "source": sale.source,
        "estimated": sale.estimated,
        "asset_type": sale.asset_type,
        "holding_id": sale.holding_id,
        "name": sale.name,
        "sold_on": sale.sold_on,
        "proceeds": money(sale.proceeds),
        "cost": money(sale.cost),
        "gain": money(sale.proceeds) - money(sale.cost),
        "class": cls,
        "flags": flags,
        "lots": out_lots,
    }


# --- Financial year totals ---------------------------------------------------------------------


def exemption_limit(start_year: int) -> Decimal:
    return EXEMPTION_NEW if start_year >= EXEMPTION_NEW_FROM_FY else EXEMPTION_OLD


def fy_totals(sales: Sequence[Mapping[str, Any]], start_year: int) -> dict[str, Any]:
    """Buckets and summary for the built sales (build_sale output) of one financial year."""
    gains = {k: _ZERO for k in BUCKET_ORDER}
    losses = {k: _ZERO for k in BUCKET_ORDER}
    present: set[str] = set()
    excluded = 0
    for sale in sales:
        for lot in sale["lots"]:
            bucket = lot["bucket"]
            if bucket is None:
                excluded += 1
                continue
            present.add(bucket)
            gain = lot["gain"]
            if gain >= 0:
                gains[bucket] += gain
            else:
                losses[bucket] += -gain
    net = {k: gains[k] - losses[k] for k in BUCKET_ORDER}
    # Set-off. `room` is the positive net still open to absorb a loss.
    room = {k: max(net[k], _ZERO) for k in BUCKET_ORDER if k != "crypto"}
    set_off = {k: _ZERO for k in BUCKET_ORDER}
    pending = {k: -net[k] if net[k] < 0 else _ZERO for k in BUCKET_ORDER if k != "crypto"}
    for source, targets in (
        *((s, _SETOFF_TARGETS_SHORT) for s in _SHORT_LOSS_ORDER),
        *((s, _SETOFF_TARGETS_LONG) for s in _LONG_LOSS_ORDER),
    ):
        for target in targets:
            if pending[source] <= 0:
                break
            if target == source or room[target] <= 0:
                continue
            take = min(pending[source], room[target])
            pending[source] -= take
            room[target] -= take
            set_off[target] += take
    total_set_off = sum(set_off.values(), _ZERO)
    unused = sum(pending.values(), _ZERO)
    # Equity long-term exemption.
    exemption = {k: _ZERO for k in BUCKET_ORDER}
    left = exemption_limit(start_year)
    for key in ("equity_lt", "equity_lt_old"):
        used = min(left, room[key])
        exemption[key] = used
        left -= used
    exemption_used = sum(exemption.values(), _ZERO)

    buckets: list[dict[str, Any]] = []
    fixed_tax = _ZERO
    slab_gains = _ZERO
    for key in BUCKET_ORDER:
        if key not in present:
            continue
        rate = BUCKET_RATES[key]
        if key == "crypto":
            taxable = gains[key]
        elif net[key] > 0:
            taxable = max(_ZERO, net[key] - set_off[key] - exemption[key])
        else:
            taxable = _ZERO
        tax = None if rate is None else (taxable * rate / 100).quantize(_CENT, ROUND_HALF_UP)
        if tax is not None:
            fixed_tax += tax
        if key == "slab":
            slab_gains = taxable
        buckets.append(
            {
                "key": key,
                "label": BUCKET_LABELS[key],
                "term": BUCKET_TERMS[key],
                "rate": rate,
                "gains": gains[key],
                "losses": losses[key],
                "net": net[key],
                "set_off": set_off[key],
                "exemption": exemption[key],
                "taxable": taxable,
                "tax": tax,
            }
        )
    summary = {
        "short_term_net": net["equity_st"] + net["equity_st_old"] + net["slab"] + net["crypto"],
        "long_term_net": net["other_lt"] + net["equity_lt"] + net["equity_lt_old"],
        "losses_set_off": total_set_off,
        "unused_losses": unused,
        "exemption_used": exemption_used,
        "fixed_rate_tax": fixed_tax,
        "slab_gains": slab_gains,
        "sales_count": len(sales),
        "excluded_lots": excluded,
    }
    return {"buckets": buckets, "summary": summary}


def sale_order(sale: Mapping[str, Any]) -> tuple[date, int, int]:
    """Sort key of a built sale: date, then exit id (computed repayments have none), then holding."""
    return (sale["sold_on"], sale["exit_id"] or 0, sale["holding_id"])


def capital_gains(
    inputs: Sequence[SaleInput], start_year: int, today: date | None = None
) -> dict[str, Any]:
    """Sales sold within the financial year `start_year`, built and totalled:
    {"buckets": [...], "sales": [...], "expected": [...], "expected_gain": x, "summary": {...}}.
    With `today`, a computed bond repayment (source not "sale") dated after today is expected,
    not a sale: it is listed in "expected" and stays out of the buckets and the summary."""
    first = date(start_year, 4, 1)
    last = date(start_year + 1, 3, 31)
    sales: list[dict[str, Any]] = []
    expected: list[dict[str, Any]] = []
    for s in inputs:
        if not first <= s.sold_on <= last:
            continue
        built = build_sale(s)
        if today is not None and s.source != "sale" and s.sold_on > today:
            expected.append(built)
        else:
            sales.append(built)
    sales.sort(key=sale_order)
    expected.sort(key=sale_order)
    totals = fy_totals(sales, start_year)
    return {
        "buckets": totals["buckets"],
        "sales": sales,
        "expected": expected,
        "expected_gain": sum((s["gain"] for s in expected), _ZERO),
        "summary": totals["summary"],
    }


# --- Bond repayments ---------------------------------------------------------------------------


def bond_repayment(
    bond: Any, master: Any, settled: Mapping[str, Any] | None = None
) -> tuple[str, Any]:
    """What a bond's repayment at the holding's maturity_date means for capital gains. The amounts
    come from the holding, never from a settlement (which may include the last coupon).

    Returns ("sale", SaleInput): face value x current quantity (SGB planned sale: issue price x
    grams) against the invested amount, source "maturity" or "planned_sale", estimated;
    ("tax_free", item dict): an SGB maturity (exempt), amount = the settled amount when `settled`
    ({"id", "amount", "cost", "date"}) is given, else issue price x grams, estimated;
    ("no_face", None): no face value (SGB: no issue price) to work with."""
    sgb = bond_schedule.is_sgb(bond, master)
    planned = bond_schedule.is_planned_sale(bond, master)
    maturity = _to_date(_field(bond, "maturity_date"))
    quantity = _dec(_field(bond, "quantity"))
    cost = money(_dec(_field(bond, "invested_amount")))
    if sgb:
        issue_price = _field(master, "issue_price")
        if not issue_price:
            if not planned and settled is not None:
                return "tax_free", {
                    "exit_id": settled["id"],
                    "holding_id": _field(bond, "id"),
                    "name": _field(bond, "name"),
                    "settled_on": settled["date"],
                    "amount": money(settled["amount"]),
                    "cost": money(settled["cost"]),
                    "gain": money(settled["amount"]) - money(settled["cost"]),
                    "estimated": False,
                }
            return "no_face", None
        face = _dec(issue_price)
    else:
        face_value = _field(bond, "face_value") or _field(master, "face_value")
        if not face_value:
            return "no_face", None
        face = _dec(face_value)
    proceeds = money(face * quantity)
    if sgb and not planned:
        if settled is not None:
            amount, base, exit_id, when, estimated = (
                money(settled["amount"]), money(settled["cost"]), settled["id"], settled["date"], False,
            )  # fmt: skip
        else:
            amount, base, exit_id, when, estimated = proceeds, cost, None, maturity, True
        return "tax_free", {
            "exit_id": exit_id,
            "holding_id": _field(bond, "id"),
            "name": _field(bond, "name"),
            "settled_on": when,
            "amount": amount,
            "cost": base,
            "gain": amount - base,
            "estimated": estimated,
        }
    master_type = _field(master, "bond_type")
    return "sale", SaleInput(
        exit_id=None,
        asset_type="bond",
        holding_id=_field(bond, "id"),
        name=_field(bond, "name"),
        sold_on=maturity,
        quantity=quantity,
        proceeds=proceeds,
        cost=cost,
        bought_on=_to_date(_field(bond, "purchase_date")),
        bond_type=master_type or _field(bond, "bond_type"),
        bond_has_master=master is not None,
        source="planned_sale" if planned else "maturity",
        estimated=True,
    )

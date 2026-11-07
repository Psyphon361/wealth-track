"""Interest income and TDS by payer, per Indian financial year (Apr-Mar). Pure functions; the
clock is a parameter.

Rules (Section 194A, FY 2025-26 onwards, regular thresholds, PAN assumed): interest is summed
per payer (a bank or company, all branches). Banks, co-operative banks and the post office
deduct above Rs 50,000; NBFCs and HFCs (company deposits) above Rs 10,000. Once the year's
interest from a payer is over its threshold (exactly at it does not count), TDS is 10% of the
whole year's interest. Banks deduct on accrual, so a cumulative FD or an RD counts the interest
accrued within the year, not only what is paid at maturity.

A window is (a, b]: interest accrued after day `a` up to and including day `b`. A financial year
is (31 Mar before, 31 Mar end]. Cumulative FD: growth at b minus growth at a, each clipped to
[start, maturity]. Payout FD: payouts dated in the window. RD: value at b minus value at a minus
instalments paid in the window. Savings: balance x rate x days / 365 (an estimate: the balance
is assumed to stand all year). The current year is reported to date (b = today) and projected
(b = 31 Mar), assuming no new deposits; the previous year has both equal to the full year.
"""

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.services import bond_schedule, valuation
from app.services.analytics import (
    _CENT,
    _ZERO,
    _clean,
    _dec,
    _field,
    _norm,
    _q,
    _to_date,
    _valued_obj,
    _FD_FIELDS,
    _RD_FIELDS,
    resolve_bank,
)

BANK_THRESHOLD = Decimal(50000)
COMPANY_THRESHOLD = Decimal(10000)
TDS_RATE = Decimal("0.10")
_COMPANY_CATEGORIES = frozenset({"nbfc", "hfc"})
# Asset-class rows of the by-class summary, in display order.
_CLASS_LABELS = {
    "fd": "Fixed Deposits",
    "rd": "Recurring Deposits",
    "bond": "Bonds",
    "savings": "Savings",
}


# --- Financial years ---------------------------------------------------------------------------


def current_fy_start_year(today: date) -> int:
    return today.year if today.month >= 4 else today.year - 1


def fy_label(start_year: int) -> str:
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def fy_bounds(start_year: int) -> tuple[date, date]:
    """(1 Apr, 31 Mar) of the financial year starting in `start_year`."""
    return date(start_year, 4, 1), date(start_year + 1, 3, 31)


def available_fys(today: date) -> list[dict[str, Any]]:
    """The current and the previous financial year, current first."""
    current = current_fy_start_year(today)
    return [
        {"start_year": year, "label": fy_label(year), "is_current": year == current}
        for year in (current, current - 1)
    ]


# --- Interest in a window (a, b] ---------------------------------------------------------------


def fd_interest(fd: Any, a: date, b: date) -> float:
    """Interest of one FD accrued (cumulative) or paid out (payout) in (a, b]."""
    maturity = valuation._maturity(fd)
    if fd.payout_type == "payout":
        flows = valuation.payout_fd_flows(
            fd.start_date, fd.compounding, fd.rate, fd.principal, b, maturity
        )
        return sum(amount for when, amount in flows if a < when <= b)

    def grown(x: date) -> float:
        clipped = min(max(x, fd.start_date), maturity)
        t = valuation._year_fraction(fd.start_date, clipped)
        return valuation._grow(fd.principal, fd.rate, fd.compounding, t)

    return grown(b) - grown(a)


def rd_interest(rd: Any, a: date, b: date) -> float:
    """Interest of one RD accrued in (a, b]: value growth less the instalments paid in it."""
    count_a, value_a = valuation.rd_position(rd, a)
    count_b, value_b = valuation.rd_position(rd, b)
    return value_b - value_a - (count_b - count_a) * float(rd.monthly_instalment)


def savings_interest(balance: Decimal, rate_pct: Decimal, a: date, b: date) -> Decimal:
    """Simple interest on a standing balance over the days in (a, b]."""
    days = max((b - a).days, 0)
    return balance * rate_pct / 100 * days / 365


def bond_coupons(bond: Any, master: Any, a: date, b: date) -> Decimal | None:
    """Coupons of one bond paid in (a, b], or None when its coupon schedule can't be worked out
    (see bond_schedule.payments for the rules)."""
    schedule = bond_schedule.payments(bond, master)
    if schedule is None:
        return None
    return bond_schedule.sum_in_window(schedule, a, b)


# --- Payers ------------------------------------------------------------------------------------


def _threshold(master: Any) -> tuple[str, Decimal]:
    if _field(master, "category") in _COMPANY_CATEGORIES:
        return "company", COMPANY_THRESHOLD
    return "bank", BANK_THRESHOLD


def _holding_label(item: Mapping[str, Any]) -> str:
    label = " ".join(str(item.get("label") or "").split())
    return label or " ".join(str(item.get("bank") or "").split()) or "Deposit"


def _bond_subtitle(item: Mapping[str, Any]) -> str | None:
    """"<quantity> units · bought <D Mon YYYY>", to tell two holdings of one bond apart."""
    quantity = item.get("quantity")
    bought = _to_date(item.get("purchase_date"))
    parts = []
    if quantity:
        parts.append(f"{quantity} units")
    if bought:
        parts.append(f"bought {bought.day} {bought:%b} {bought.year}")
    return " · ".join(parts) or None


def _free_item(
    kind: str, item: Mapping[str, Any], to_date: Decimal, projected: Decimal
) -> dict[str, Any]:
    return {
        "kind": kind,
        "id": item["id"],
        "name": _clean(item.get("name")) or kind.upper(),
        "interest_to_date": to_date,
        "interest_projected": projected,
    }


def tax_overview(
    groups: Sequence[Mapping[str, Any]],
    issuer_masters: Mapping[Any, Any] | None,
    today: date,
    fy_start_year: int | None = None,
    bond_masters: Mapping[Any, Any] | None = None,
) -> dict[str, Any]:
    """The tax tab response for the financial year starting in `fy_start_year` (default: the
    current one). FDs and RDs count whether active or matured: a deposit that matured this year
    still earned its interest this year. Bond coupons count on their payment dates; each issuer
    is a payer (10% TDS on every coupon of a corporate bond, none for government securities and
    SGBs).
    Tax-free bonds and PPF / EPF / VPF interest go to the tax-free total instead of a payer."""
    issuer_masters = issuer_masters or {}
    bond_masters = bond_masters or {}
    current = current_fy_start_year(today)
    year = current if fy_start_year is None else fy_start_year
    is_current = year == current
    start, end = fy_bounds(year)
    a = start - timedelta(days=1)
    to_date_end = min(today, end) if is_current else end
    window_to_date = (a, to_date_end)
    window_full = (a, end)

    payers: dict[str, dict[str, Any]] = {}
    bonds = 0
    savings_total = _ZERO
    savings_to_date = _ZERO
    savings_accounts = 0
    free_items: list[dict[str, Any]] = []
    for group in groups:
        kind = group["type"]
        for item in group.get("items", []):
            if kind == "bond":
                master = bond_masters.get(item.get("master_id"))
                schedule = bond_schedule.payments(item, master)
                if schedule is None:
                    bonds += 1
                    continue
                sold_on = _to_date(item.get("closed_on"))
                if sold_on is not None:
                    # Sold before maturity: only the coupons up to the sale were earned.
                    schedule = [
                        p for p in schedule if p["kind"] == "coupon" and p["date"] <= sold_on
                    ]
                projected_q = _q(bond_schedule.sum_in_window(schedule, *window_full))
                if projected_q <= 0:
                    continue
                to_date = _q(bond_schedule.sum_in_window(schedule, *window_to_date))
                bond_type = item.get("bond_type")
                master_type = _field(master, "bond_type")
                if "tax_free" in (bond_type, master_type):
                    free_items.append(
                        _free_item("tax_free_bond", item, to_date, projected_q)
                    )
                    continue
                issuer = _clean(_field(master, "issuer") or item.get("issuer")) or "Unknown issuer"
                entry = payers.setdefault(
                    f"bond:{_norm(issuer)}", {"bank": None, "name": issuer, "holdings": []}
                )
                entry["no_tds"] = entry.get("no_tds", True) and not bond_schedule.tds_applies(
                    item, master
                )
                entry["holdings"].append(
                    {
                        "id": item["id"],
                        "type": "bond",
                        "name": _clean(item.get("name")) or issuer,
                        "interest_to_date": to_date,
                        "interest_projected": projected_q,
                        "tds_estimate": _q(
                            bond_schedule.sum_in_window(schedule, *window_full, "tds")
                        ),
                        "subtitle": _bond_subtitle(item),
                        "payments": [
                            {
                                "date": p["date"],
                                "gross": _q(p["gross"]),
                                "tds": _q(p["tds"]),
                                "net": _q(p["gross"] - p["tds"]),
                                "paid": p["date"] <= today,
                            }
                            for p in schedule
                            if p["kind"] == "coupon" and window_full[0] < p["date"] <= end
                        ],
                    }
                )
            elif kind == "pf":
                rate = item.get("interest_rate")
                balance_date = _to_date(item.get("balance_date"))
                if item.get("kind") not in ("ppf", "epf", "vpf") or not rate or not balance_date:
                    continue
                balance = _dec(item.get("balance"))
                rate = _dec(rate)
                projected_q = _q(
                    savings_interest(balance, rate, max(a, balance_date), end)
                )
                if projected_q <= 0:
                    continue
                to_date = _q(
                    savings_interest(balance, rate, max(a, balance_date), to_date_end)
                )
                free_items.append(_free_item(item["kind"], item, to_date, projected_q))
            elif kind == "cash":
                rate = item.get("interest_rate")
                if item.get("kind") != "savings" or not rate:
                    continue
                balance = Decimal(str(item.get("balance") or 0))
                interest = savings_interest(balance, Decimal(str(rate)), *window_full)
                if interest > 0:
                    savings_total += interest
                    savings_to_date += savings_interest(
                        balance, Decimal(str(rate)), *window_to_date
                    )
                    savings_accounts += 1
            elif kind in ("fd", "rd"):
                if kind == "fd":
                    obj = _valued_obj(item, **_FD_FIELDS)
                    to_date = fd_interest(obj, *window_to_date)
                    projected = fd_interest(obj, *window_full)
                else:
                    obj = _valued_obj(item, **_RD_FIELDS)
                    to_date = rd_interest(obj, *window_to_date)
                    projected = rd_interest(obj, *window_full)
                projected_q = _q(Decimal(str(projected)))
                if projected_q <= 0:
                    continue
                bank = resolve_bank(item, issuer_masters)
                entry = payers.setdefault(
                    bank.key, {"bank": bank, "name": bank.name, "holdings": []}
                )
                entry["holdings"].append(
                    {
                        "id": item["id"],
                        "type": kind,
                        "name": _holding_label(item),
                        "interest_to_date": _q(Decimal(str(to_date))),
                        "interest_projected": projected_q,
                    }
                )

    rows = []
    for key, entry in payers.items():
        bank = entry["bank"]
        threshold = None
        if bank is None:
            payer_kind = "bond"
            tds_rule = "none" if entry["no_tds"] else "every_payment"
        else:
            master = issuer_masters.get(bank.issuer_id) if bank.issuer_id is not None else None
            payer_kind, threshold = _threshold(master)
            tds_rule = "threshold"
        holdings = sorted(
            entry["holdings"], key=lambda h: (-h["interest_projected"], h["type"], h["id"])
        )
        to_date = sum((h["interest_to_date"] for h in holdings), _ZERO)
        projected = sum((h["interest_projected"] for h in holdings), _ZERO)
        crosses = threshold is not None and projected > threshold
        if tds_rule == "threshold":
            tds = _q(projected * TDS_RATE) if crosses else Decimal("0.00")
            # Split the payer's TDS by each holding's share of its projected interest.
            for h in holdings:
                share = h["interest_projected"] / projected if projected else _ZERO
                h["tds_estimate"] = _q(tds * share) if crosses else Decimal("0.00")
        else:
            tds = sum((h["tds_estimate"] for h in holdings), _ZERO)
        rows.append(
            {
                "key": key,
                "name": entry["name"],
                "kind": payer_kind,
                "tds_rule": tds_rule,
                "threshold": None if threshold is None else threshold.quantize(_CENT),
                "interest_to_date": to_date,
                "interest_projected": projected,
                "crosses": crosses,
                "tds_estimate": tds,
                "holdings": holdings,
            }
        )
    rows.sort(key=lambda r: (-r["interest_projected"], r["name"].casefold(), r["key"]))

    savings = None
    if savings_accounts:
        savings = {"interest_estimate": _q(savings_total), "accounts": savings_accounts}
    free_items.sort(key=lambda i: (-i["interest_projected"], i["kind"], i["id"]))
    taxable = {
        "interest_to_date": sum((r["interest_to_date"] for r in rows), _ZERO)
        + _q(savings_to_date),
        "interest_projected": sum((r["interest_projected"] for r in rows), _ZERO)
        + _q(savings_total),
    }
    tax_free = {
        "interest_to_date": sum((i["interest_to_date"] for i in free_items), _ZERO),
        "interest_projected": sum((i["interest_projected"] for i in free_items), _ZERO),
        "items": free_items,
    }
    by_class = []
    for slug, label in _CLASS_LABELS.items():
        if slug == "savings":
            if not savings_accounts:
                continue
            by_class.append(
                {
                    "type": slug,
                    "label": label,
                    "interest_to_date": _q(savings_to_date),
                    "interest_projected": _q(savings_total),
                    "tds_estimate": Decimal("0.00"),
                    "holdings_count": savings_accounts,
                }
            )
            continue
        held = [h for r in rows for h in r["holdings"] if h["type"] == slug]
        if not held:
            continue
        by_class.append(
            {
                "type": slug,
                "label": label,
                "interest_to_date": sum((h["interest_to_date"] for h in held), _ZERO),
                "interest_projected": sum((h["interest_projected"] for h in held), _ZERO),
                "tds_estimate": sum((h["tds_estimate"] for h in held), _ZERO),
                "holdings_count": len(held),
            }
        )
    return {
        "fy": fy_label(year),
        "fy_start": start,
        "fy_end": end,
        "as_of": today,
        "is_current": is_current,
        "available_fys": available_fys(today),
        "payers": rows,
        "by_class": by_class,
        "totals": {
            "interest_to_date": sum((r["interest_to_date"] for r in rows), _ZERO),
            "interest_projected": sum((r["interest_projected"] for r in rows), _ZERO),
            "tds_estimate": sum((r["tds_estimate"] for r in rows), _ZERO),
        },
        "savings": savings,
        "taxable": taxable,
        "tax_free": tax_free,
        "excluded": {"bonds": bonds},
    }

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

from app.services import valuation
from app.services.analytics import (
    _CENT,
    _ZERO,
    _field,
    _q,
    _valued_obj,
    _FD_FIELDS,
    _RD_FIELDS,
    resolve_bank,
)

BANK_THRESHOLD = Decimal(50000)
COMPANY_THRESHOLD = Decimal(10000)
TDS_RATE = Decimal("0.10")
_COMPANY_CATEGORIES = frozenset({"nbfc", "hfc"})


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


# --- Payers ------------------------------------------------------------------------------------


def _threshold(master: Any) -> tuple[str, Decimal]:
    if _field(master, "category") in _COMPANY_CATEGORIES:
        return "company", COMPANY_THRESHOLD
    return "bank", BANK_THRESHOLD


def _holding_label(item: Mapping[str, Any]) -> str:
    label = " ".join(str(item.get("label") or "").split())
    return label or " ".join(str(item.get("bank") or "").split()) or "Deposit"


def tax_overview(
    groups: Sequence[Mapping[str, Any]],
    issuer_masters: Mapping[Any, Any] | None,
    today: date,
    fy_start_year: int | None = None,
) -> dict[str, Any]:
    """The tax tab response for the financial year starting in `fy_start_year` (default: the
    current one). FDs and RDs count whether active or matured: a deposit that matured this year
    still earned its interest this year."""
    issuer_masters = issuer_masters or {}
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
    savings_accounts = 0
    for group in groups:
        kind = group["type"]
        for item in group.get("items", []):
            if kind == "bond":
                bonds += 1
            elif kind == "cash":
                rate = item.get("interest_rate")
                if item.get("kind") != "savings" or not rate:
                    continue
                balance = Decimal(str(item.get("balance") or 0))
                interest = savings_interest(balance, Decimal(str(rate)), *window_full)
                if interest > 0:
                    savings_total += interest
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
                entry = payers.setdefault(bank.key, {"bank": bank, "holdings": []})
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
        master = issuer_masters.get(bank.issuer_id) if bank.issuer_id is not None else None
        payer_kind, threshold = _threshold(master)
        holdings = sorted(entry["holdings"], key=lambda h: (-h["interest_projected"], h["id"]))
        to_date = sum((h["interest_to_date"] for h in holdings), _ZERO)
        projected = sum((h["interest_projected"] for h in holdings), _ZERO)
        crosses = projected > threshold
        rows.append(
            {
                "key": key,
                "name": bank.name,
                "kind": payer_kind,
                "threshold": threshold.quantize(_CENT),
                "interest_to_date": to_date,
                "interest_projected": projected,
                "crosses": crosses,
                "tds_estimate": _q(projected * TDS_RATE) if crosses else Decimal("0.00"),
                "holdings": holdings,
            }
        )
    rows.sort(key=lambda r: (-r["interest_projected"], r["name"].casefold(), r["key"]))

    savings = None
    if savings_accounts:
        savings = {"interest_estimate": _q(savings_total), "accounts": savings_accounts}
    return {
        "fy": fy_label(year),
        "fy_start": start,
        "fy_end": end,
        "as_of": today,
        "is_current": is_current,
        "available_fys": available_fys(today),
        "payers": rows,
        "totals": {
            "interest_to_date": sum((r["interest_to_date"] for r in rows), _ZERO),
            "interest_projected": sum((r["interest_projected"] for r in rows), _ZERO),
            "tds_estimate": sum((r["tds_estimate"] for r in rows), _ZERO),
        },
        "savings": savings,
        "excluded": {"bonds": bonds},
    }

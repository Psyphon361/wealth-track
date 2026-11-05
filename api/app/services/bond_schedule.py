"""Estimated payment schedule of one bond: every coupon from the purchase date to maturity plus the
redemption at maturity. Pure functions; no clock.

Dates are estimates: the frequency and rate come from the linked bond_master, and coupon dates are
stepped back from the maturity date every 12 / n months (clamped to the month end), counted when
after the purchase date. An SGB pays half-yearly 2.5% on the issue price per gram (quantity is
grams) and redeems at the issue price x grams (an estimate: the real value follows the gold
price). An on-maturity bond pays its whole interest (simple, or compounded yearly) on the maturity
date. TDS is 10% of every coupon on corporate and other bonds; government securities, SGBs and
tax-free bonds have none; redemption never has TDS.

Amounts are unrounded Decimals; callers round for display.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from dateutil.relativedelta import relativedelta

from app.services import valuation
from app.services.analytics import _ZERO, _dec, _field, _to_date

TDS_RATE = Decimal("0.10")
SGB_RATE = Decimal("2.5")
# Coupon payments a year for each master interest_frequency that has a regular schedule.
COUPONS_PER_YEAR = {"yearly": 1, "half_yearly": 2, "quarterly": 4, "monthly": 12}
# Bond types on which no TDS is deducted (government securities, SGBs, tax-free bonds).
NO_TDS_TYPES = frozenset({"government", "sgb", "tax_free"})


def fy_of(when: date) -> str:
    """Indian financial year of a date, e.g. "2026-27"."""
    start = when.year if when.month >= 4 else when.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def is_sgb(bond: Any, master: Any) -> bool:
    return _field(bond, "bond_type") == "sgb" or _field(master, "bond_type") == "sgb"


def tds_applies(bond: Any, master: Any) -> bool:
    """Whether coupons of this bond carry 10% TDS."""
    return _field(bond, "bond_type") not in NO_TDS_TYPES and (
        _field(master, "bond_type") not in NO_TDS_TYPES
    )


def _payment(when: date, kind: str, gross: Decimal, tds: Decimal, **extra: Any) -> dict[str, Any]:
    # Rounded to paise here: that is how a real coupon is paid, so every sum is exact.
    gross = _q(gross)
    tds = _q(tds)
    return {
        "date": when,
        "kind": kind,
        "gross": gross,
        "tds": tds,
        "net": gross - tds,
        "fy": fy_of(when),
        **extra,
    }


def payments(bond: Any, master: Any) -> list[dict[str, Any]] | None:
    """Every estimated payment of one bond, oldest first, or None when its schedule can't be
    worked out (no linked master, no coupon rate, frequency none / irregular / unknown, missing
    dates or quantity). Each payment: date, kind (coupon | redemption), gross, tds, net, fy; a
    redemption also carries estimated_value (True for an SGB)."""
    if master is None:
        return None
    maturity = _to_date(_field(bond, "maturity_date"))
    purchase = _to_date(_field(bond, "purchase_date"))
    quantity = _field(bond, "quantity")
    if maturity is None or purchase is None or not quantity:
        return None
    taxed = tds_applies(bond, master)
    out: list[dict[str, Any]] = []
    sgb = is_sgb(bond, master)
    if sgb:
        rate = _field(master, "coupon_rate")
        rate = _dec(rate) if rate else SGB_RATE
        issue_price = _field(master, "issue_price")
        if not issue_price:
            return None
        per_coupon = _dec(issue_price) * quantity * rate / 100 / 2
        redemption = _dec(issue_price) * quantity
        step = 6
    else:
        rate = _field(master, "coupon_rate")
        face = _field(bond, "face_value") or _field(master, "face_value")
        frequency = _field(master, "interest_frequency")
        if not rate or not face:
            return None
        principal = _dec(face) * quantity
        redemption = principal
        if frequency == "on_maturity":
            issue = _to_date(_field(master, "issue_date"))
            if issue is None or maturity <= issue:
                return None
            t = valuation._year_fraction(issue, maturity)
            if _field(master, "coupon_type") == "compounding":
                grown = valuation._grow(principal, _dec(rate), "yearly", t)
            else:
                grown = valuation._grow(principal, _dec(rate), "simple", t)
            gross = Decimal(str(grown)) - principal
            out.append(_payment(maturity, "coupon", gross, gross * TDS_RATE if taxed else _ZERO))
            out.append(_payment(maturity, "redemption", redemption, _ZERO, estimated_value=False))
            return out
        count = COUPONS_PER_YEAR.get(frequency)
        if count is None:
            return None
        per_coupon = principal * _dec(rate) / 100 / count
        step = 12 // count
    coupons: list[dict[str, Any]] = []
    k = 0
    while True:
        when = maturity - relativedelta(months=step * k)
        if when <= purchase:
            break
        coupons.append(
            _payment(when, "coupon", per_coupon, per_coupon * TDS_RATE if taxed else _ZERO)
        )
        k += 1
    coupons.reverse()
    out.extend(coupons)
    out.append(_payment(maturity, "redemption", redemption, _ZERO, estimated_value=sgb))
    return out


def sum_in_window(
    schedule: list[dict[str, Any]], a: date, b: date, field: str = "gross"
) -> Decimal:
    """Sum of `field` over the coupons dated in (a, b]."""
    return sum(
        (p[field] for p in schedule if p["kind"] == "coupon" and a < p["date"] <= b), _ZERO
    )


def by_fy(schedule: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Coupon totals per financial year, oldest first: fy, coupons (count), gross, tds, net."""
    rows: dict[str, dict[str, Any]] = {}
    for p in schedule:
        if p["kind"] != "coupon":
            continue
        row = rows.setdefault(
            p["fy"], {"fy": p["fy"], "coupons": 0, "gross": _ZERO, "tds": _ZERO, "net": _ZERO}
        )
        row["coupons"] += 1
        row["gross"] += p["gross"]
        row["tds"] += p["tds"]
        row["net"] += p["net"]
    return list(rows.values())


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def schedule_view(bond: Any, master: Any, today: date) -> dict[str, Any] | None:
    """One bond for GET /api/analytics/bond-schedule: its details, every payment (amounts rounded
    to paise, `paid` when dated on or before today), the next unpaid payment and coupon totals per
    financial year. None when the schedule can't be worked out."""
    schedule = payments(bond, master)
    if schedule is None:
        return None
    rows = []
    for p in schedule:
        row = {
            "date": p["date"],
            "kind": p["kind"],
            "gross": _q(p["gross"]),
            "tds": _q(p["tds"]),
            "net": _q(p["gross"] - p["tds"]),
            "fy": p["fy"],
            "paid": p["date"] <= today,
        }
        if p["kind"] == "redemption":
            row["estimated_value"] = p["estimated_value"]
        rows.append(row)
    face = _field(bond, "face_value") or _field(master, "face_value")
    rate = _field(master, "coupon_rate")
    issuer = _field(master, "issuer") or _field(bond, "issuer")
    return {
        "id": _field(bond, "id"),
        "name": " ".join(str(_field(bond, "name") or issuer or "Bond").split()),
        "issuer": " ".join(str(issuer or "").split()) or None,
        "bond_type": _field(bond, "bond_type"),
        "coupon_rate": None if rate is None else _dec(rate),
        "frequency": "half_yearly" if is_sgb(bond, master) else _field(master, "interest_frequency"),
        "face_value": None if face is None else _dec(face),
        "quantity": _field(bond, "quantity"),
        "purchase_date": _to_date(_field(bond, "purchase_date")),
        "maturity_date": _to_date(_field(bond, "maturity_date")),
        "tds_rate": _dec(10) if tds_applies(bond, master) else _dec(0),
        "estimated": True,
        "payments": rows,
        "next_payment": next((r for r in rows if not r["paid"]), None),
        "by_fy": [
            {
                "fy": r["fy"],
                "coupons": r["coupons"],
                "gross": _q(r["gross"]),
                "tds": _q(r["tds"]),
                "net": _q(r["gross"] - r["tds"]),
            }
            for r in by_fy(schedule)
        ],
    }

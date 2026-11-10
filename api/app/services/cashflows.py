"""Money coming in: dated inflow events from the user's active deposits and bonds. Pure functions;
the clock is a parameter.

Events, each split into `interest` and `principal` (gross, before any TDS):
- Bonds: every coupon (kind coupon, interest) and the redemption at maturity (kind redemption,
  principal), from bond_schedule; a bond sold before its maturity gives its coupons up to the exit
  date and then a sale (kind sale, principal) instead of a redemption. A bond without a workable
  schedule gives nothing.
- Payout FD: each interest payout (kind interest_payout) and the principal at maturity (kind
  maturity).
- Cumulative FD: one maturity event, principal plus all the interest.
- RD: one maturity event, the instalments paid (principal) plus the interest.
Only active holdings count, and only events dated from today on. Stocks, MF, NPS, gold, cash, PF
and Other give nothing.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from dateutil.relativedelta import relativedelta

from app.services import bond_schedule, valuation
from app.services.analytics import (
    _ZERO,
    _clean,
    _q,
    _valued_obj,
    _FD_FIELDS,
    _RD_FIELDS,
)

TYPE_ORDER = ("fd", "rd", "bond")


def _label(item: Mapping[str, Any]) -> str:
    label = _clean(item.get("label"))
    return label or _clean(item.get("bank")) or "Deposit"


def _event(
    when: date, kind: str, type_: str, item: Mapping[str, Any], name: str,
    interest: Decimal, principal: Decimal,
) -> dict[str, Any]:  # fmt: skip
    return {
        "date": when,
        "type": type_,
        "id": item["id"],
        "name": name,
        "kind": kind,
        "interest": interest,
        "principal": principal,
    }


def _fd_events(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    fd = _valued_obj(item, **_FD_FIELDS)
    maturity = valuation._maturity(fd)
    name = _label(item)
    if fd.payout_type == "payout":
        flows = valuation.payout_fd_flows(
            fd.start_date, fd.compounding, fd.rate, fd.principal, maturity, maturity
        )
        out = [
            _event(when, "interest_payout", "fd", item, name, _q(Decimal(str(amount))), _ZERO)
            for when, amount in flows
            if _q(Decimal(str(amount))) > 0
        ]
        out.append(_event(maturity, "maturity", "fd", item, name, _ZERO, _q(Decimal(fd.principal))))
        return out
    value = valuation.value_fd(fd, maturity)
    principal = _q(Decimal(fd.principal))
    return [
        _event(
            maturity, "maturity", "fd", item, name,
            _q(value["current_value"]) - principal, principal,
        )  # fmt: skip
    ]


def _rd_events(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    rd = _valued_obj(item, **_RD_FIELDS)
    maturity = valuation._maturity(rd)
    value = valuation.value_rd(rd, maturity)
    principal = _q(value["invested"])
    return [
        _event(
            maturity, "maturity", "rd", item, _label(item),
            _q(value["current_value"]) - principal, principal,
        )  # fmt: skip
    ]


def _bond_events(item: Mapping[str, Any], master: Any) -> list[dict[str, Any]]:
    schedule = bond_schedule.payments(item, master)
    if schedule is None:
        return []
    name = _clean(item.get("name")) or _clean(item.get("issuer")) or "Bond"
    out = []
    for p in schedule:
        if p["kind"] == "coupon":
            out.append(_event(p["date"], "coupon", "bond", item, name, _q(p["gross"]), _ZERO))
        else:  # redemption or sale: principal only
            out.append(_event(p["date"], p["kind"], "bond", item, name, _ZERO, _q(p["gross"])))
    return out


def inflow_events(
    groups: Sequence[Mapping[str, Any]],
    bond_masters: Mapping[Any, Any] | None,
) -> list[dict[str, Any]]:
    """Every future-and-past inflow event of the active FDs, RDs and bonds, unsorted."""
    bond_masters = bond_masters or {}
    events: list[dict[str, Any]] = []
    for group in groups:
        kind = group["type"]
        if kind not in TYPE_ORDER:
            continue
        for item in group.get("items", []):
            if item.get("status") != "active":
                continue
            if kind == "fd":
                events.extend(_fd_events(item))
            elif kind == "rd":
                events.extend(_rd_events(item))
            else:
                events.extend(_bond_events(item, bond_masters.get(item.get("master_id"))))
    return events


def inflows(
    groups: Sequence[Mapping[str, Any]],
    bond_masters: Mapping[Any, Any] | None,
    today: date,
    months: int = 12,
) -> dict[str, Any]:
    """The inflows response: `months` calendar months starting with the current one (empty months
    included), each with its items (dated from today on) and interest / principal totals."""
    first = today.replace(day=1)
    end = first + relativedelta(months=months)
    buckets = [first + relativedelta(months=k) for k in range(months)]
    by_month: dict[str, list[dict[str, Any]]] = {f"{m.year}-{m.month:02d}": [] for m in buckets}
    for event in inflow_events(groups, bond_masters):
        when = event["date"]
        if when < today or when >= end:
            continue
        by_month[f"{when.year}-{when.month:02d}"].append(event)
    rows = []
    present: set[str] = set()
    for month, items in by_month.items():
        items.sort(key=lambda e: (e["date"], e["name"].casefold(), e["type"], e["id"], e["kind"]))
        present.update(e["type"] for e in items)
        rows.append(
            {
                "month": month,
                "interest": sum((e["interest"] for e in items), _ZERO),
                "principal": sum((e["principal"] for e in items), _ZERO),
                "items": items,
            }
        )
    return {
        "as_of": today,
        "months": rows,
        "totals": {
            "interest": sum((r["interest"] for r in rows), _ZERO),
            "principal": sum((r["principal"] for r in rows), _ZERO),
        },
        "types": [t for t in TYPE_ORDER if t in present],
    }

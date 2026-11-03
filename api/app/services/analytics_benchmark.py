"""Benchmark block of the Returns endpoint: the same cash flows replayed into a Nifty 50 index
fund (public-market equivalent), the user's FD rate and CPI inflation. Pure maths; the NAV
history is passed in. See SPEC §9 "Returns"."""

import csv
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from sqlalchemy.orm import Session

from app.models.mf_master import MFNavHistorySync
from app.services.nav_history import (
    BENCHMARK_SCHEME_CODE,
    REFRESH_AFTER,
    NavRow,
    fetch_mfapi,
    pick_on_or_before,
    store_history,
)
from app.services.valuation import xirr

logger = logging.getLogger(__name__)

BENCHMARK_LABEL = "Nifty 50 index fund"
CPI_FILE = Path(__file__).resolve().parents[2] / "data" / "cpi_india.csv"
MIN_ANNUALISED_DAYS = 365
ZERO = Decimal("0")
CENT = Decimal("0.01")
HUNDRED = Decimal(100)

Flows = list[tuple[date, Decimal]]


@dataclass(frozen=True)
class BenchmarkNavs:
    scheme_name: str
    rows: list[NavRow]  # (nav_date, nav); latest NAV is the last by date


def refresh_benchmark_history(session: Session) -> bool:
    """Daily-import hook: refetch the benchmark's history (mfapi.in) when it was never synced or
    the sync is older than 24 h. Failures are logged, never raised. True when refetched."""
    sync = session.get(MFNavHistorySync, BENCHMARK_SCHEME_CODE)
    now = datetime.now(timezone.utc)
    if sync is not None and now - sync.fetched_at <= REFRESH_AFTER:
        return False
    try:
        rows = fetch_mfapi(BENCHMARK_SCHEME_CODE)
        store_history(session, BENCHMARK_SCHEME_CODE, rows, now.date(), now)
    except Exception:  # noqa: BLE001 - best effort, never fail the import
        session.rollback()
        logger.warning("Benchmark NAV sync failed", exc_info=True)
        return False
    return True


def load_cpi(path: Path = CPI_FILE) -> dict[int, Decimal]:
    """{calendar year: annual CPI inflation %} from the seed CSV (lines starting # are comments)."""
    with path.open(newline="", encoding="utf-8") as handle:
        lines = [line for line in handle if line.strip() and not line.startswith("#")]
    return {
        int(row["year"]): Decimal(row["cpi_inflation_pct"]) for row in csv.DictReader(lines)
    }


def _q(value: Decimal) -> Decimal:
    return value.quantize(CENT)


def replay(
    flows: Sequence[tuple[date, Decimal]], rows: list[NavRow], today: date
) -> tuple[Decimal | None, bool]:
    """(benchmark %, annualised) for the same flows invested in the index fund.

    Outflows buy units at the NAV on or before their date, inflows dated before today sell units,
    and the units left are worth the latest NAV today (this replaces the flows dated today, which
    are the holdings' current values). XIRR when the earliest flow is at least 365 days old, else
    the absolute return. None when a flow predates the first NAV or the result can't be computed.
    """
    earliest = min(d for d, _ in flows)
    annualised = (today - earliest).days >= MIN_ANNUALISED_DAYS
    if not rows:
        return None, annualised
    units = ZERO
    kept: Flows = []
    for day, amount in sorted(flows, key=lambda f: f[0]):
        if day >= today and amount > 0:
            continue  # terminal value, replaced below
        picked = pick_on_or_before(rows, day)
        if picked is None:
            return None, annualised
        units += -amount / picked[1]  # outflow (negative) buys, inflow sells
        kept.append((day, amount))
    latest_nav = max(rows, key=lambda r: r[0])[1]
    terminal = units * latest_nav
    if annualised:
        rate = xirr([*kept, (today, terminal)])
        return (_q(rate * HUNDRED) if rate is not None else None), True
    outflow = -sum((a for _, a in kept if a < 0), ZERO)
    if outflow <= 0:
        return None, False
    inflow = sum((a for _, a in kept if a > 0), ZERO)
    return _q((terminal + inflow - outflow) * HUNDRED / outflow), False


def fd_rate(groups: Sequence[Mapping[str, Any]]) -> Decimal | None:
    """Principal-weighted average rate of the active FDs; None without any."""
    weight = ZERO
    total = ZERO
    for group in groups:
        if group["type"] != "fd":
            continue
        for item in group.get("items", []):
            if item.get("status") != "active" or item.get("rate") is None:
                continue
            principal = Decimal(str(item.get("principal") or 0))
            weight += principal
            total += principal * Decimal(str(item["rate"]))
    return _q(total / weight) if weight > 0 else None


def inflation(
    since: date | None, cpi: Mapping[int, Decimal]
) -> tuple[Decimal | None, str | None]:
    """Compounded annual average CPI inflation % from `since`'s year to the latest year in the
    data, and the span label ("2021–2025"). (None, None) when the years don't overlap."""
    if since is None or not cpi:
        return None, None
    last = max(cpi)
    first = max(since.year, min(cpi))
    if first > last:
        return None, None
    years = [y for y in range(first, last + 1) if y in cpi]
    if not years:
        return None, None
    growth = 1.0
    for year in years:
        growth *= 1 + float(cpi[year]) / 100
    rate = Decimal(str(growth ** (1 / len(years)) - 1)) * HUNDRED
    label = str(first) if first == last else f"{first}–{last}"
    return _q(rate), label


def benchmark(
    class_flows: Mapping[str, Flows],
    all_flows: Flows,
    groups_returns: Mapping[str, tuple[Decimal | None, bool]],
    overall: tuple[Decimal | None, bool] | None,
    since: date | None,
    navs: BenchmarkNavs,
    groups: Sequence[Mapping[str, Any]],
    today: date,
    cpi: Mapping[int, Decimal],
) -> dict[str, Any]:
    """The `benchmark` response block. `groups_returns` maps a class to its (return %, annualised)."""

    def compare(flows: Flows, own: tuple[Decimal | None, bool]) -> dict[str, Any]:
        pct, annualised = replay(flows, navs.rows, today)
        return {"your_pct": own[0], "benchmark_pct": pct, "annualised": annualised}

    equity = class_flows.get("equity")  # empty list when no equity holding has flows
    infl, period = inflation(since, cpi)
    return {
        "label": BENCHMARK_LABEL,
        "scheme_name": navs.scheme_name,
        "nav_date": max((d for d, _ in navs.rows), default=None),
        "equity": compare(equity, groups_returns["equity"]) if equity else None,
        "overall": compare(all_flows, overall) if overall and all_flows else None,
        "fd_rate": fd_rate(groups),
        "inflation_pct": infl,
        "inflation_period": period,
    }

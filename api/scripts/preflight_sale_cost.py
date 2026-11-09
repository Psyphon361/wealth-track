"""Read-only preflight for FIFO sale cost of mutual funds.

Usage: DATABASE_URL=... python scripts/preflight_sale_cost.py   (or pass the URL as the first argument)

A partial fund sale will use FIFO cost only when the fund's invested amount equals the FIFO cost
of the units still held (per its mf_transactions) within 1.00. This lists live, open funds with
transactions whose units match the transactions but whose invested amount differs from the FIFO
cost by more than 1.00. The transaction is READ ONLY; the connection string is never printed.
Exit code 1 when any gap is found, 2 when it could not run, else 0.
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.models import MFTransaction, MutualFund  # noqa: E402
from app.services.exits import fifo_cost, net_units  # noqa: E402

UNITS_TOLERANCE = Decimal("0.01")
COST_TOLERANCE = Decimal("1.00")


def find_gaps(session: Session) -> tuple[list[dict], dict[str, int]]:
    """(gap rows, totals) for the live, open funds that have transactions."""
    txns: dict[int, list[MFTransaction]] = defaultdict(list)
    for t in session.scalars(select(MFTransaction)):
        txns[t.mutual_fund_id].append(t)
    funds = session.scalars(
        select(MutualFund)
        .where(MutualFund.deleted_at.is_(None), MutualFund.closed_on.is_(None))
        .order_by(MutualFund.id)
    )
    totals = {"with_transactions": 0, "units_match": 0, "gaps": 0, "skipped": 0}
    gaps: list[dict] = []
    for fund in funds:
        rows = txns.get(fund.id)
        if not rows:
            continue
        totals["with_transactions"] += 1
        units = Decimal(str(fund.units))
        if abs(net_units(rows) - units) > UNITS_TOLERANCE:
            continue
        totals["units_match"] += 1
        try:
            cost = fifo_cost(rows, units)
        except ValueError:
            totals["skipped"] += 1
            continue
        invested = Decimal(str(fund.invested_amount))
        diff = invested - cost
        if abs(diff) > COST_TOLERANCE:
            totals["gaps"] += 1
            gaps.append(
                {"fund_id": fund.id, "user_id": fund.user_id, "invested": invested, "fifo_cost": cost, "difference": diff}
            )
    return gaps, totals


def report(gaps: list[dict], totals: dict[str, int]) -> int:
    for g in gaps:
        print(", ".join(f"{k}={v}" for k, v in g.items()))
    print(
        f"funds with transactions={totals['with_transactions']}, units matching={totals['units_match']}, "
        f"gaps={totals['gaps']}, skipped={totals['skipped']}"
    )
    return 1 if gaps else 0


def main(argv: list[str]) -> int:
    url = argv[1] if len(argv) > 1 else os.environ.get("DATABASE_URL", "")
    if not url:
        print("No database URL: set DATABASE_URL or pass it as the first argument.")
        return 2
    try:
        from check_invariants import open_readonly

        conn = open_readonly(url)
        try:
            with Session(bind=conn) as session:
                gaps, totals = find_gaps(session)
        finally:
            conn.rollback()
            conn.close()
    except Exception as exc:  # never print the message: it can contain the connection string
        print(f"Could not run the check ({type(exc).__name__}).")
        return 2
    return report(gaps, totals)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main(sys.argv))

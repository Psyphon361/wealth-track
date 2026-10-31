"""Backfill month-end closes of held stocks: `python -m app.jobs.stock_history_backfill [--months 12]`."""

import argparse
from datetime import date

from app.db import SessionLocal, get_engine
from app.services import stock_history


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--months", type=int, default=12)
    args = parser.parse_args()
    get_engine()
    with SessionLocal() as session:
        result = stock_history.backfill_month_ends(session, date.today(), args.months)
    print(
        f"stocks={result.stocks} rows={result.rows} "
        f"months_fetched={result.months_fetched} months_missed={result.months_missed}"
    )
    for error in result.errors:
        print(f"error: {error}")


if __name__ == "__main__":
    main()

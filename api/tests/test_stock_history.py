from datetime import date
from decimal import Decimal

from app.services.stock_history import month_ends, rows_for_held, split_by_source


def test_month_ends_mid_month():
    ends = month_ends(date(2026, 10, 31), 12)
    assert len(ends) == 12
    assert ends[0] == date(2025, 10, 31)
    assert ends[-1] == date(2026, 9, 30)
    assert date(2026, 2, 28) in ends
    assert ends == sorted(ends)


def test_month_ends_year_boundary_and_leap_year():
    assert month_ends(date(2024, 3, 5), 3) == [date(2023, 12, 31), date(2024, 1, 31), date(2024, 2, 29)]


def test_rows_for_held_only_held_isins_with_row_dates():
    closes = {
        "INE000000001": {"price": Decimal("10.50"), "trade_date": date(2026, 10, 30)},
        "INE000000002": {"price": Decimal("20.00"), "trade_date": date(2026, 10, 30)},
        "INE000000003": {"price": Decimal("0"), "trade_date": date(2026, 10, 30)},
    }
    held = {"INE000000001": 1, "INE000000003": 3, "INE000000009": 9}
    assert rows_for_held(closes, held) == [
        {"master_id": 1, "trade_date": date(2026, 10, 30), "close": Decimal("10.50")}
    ]


def test_rows_for_held_date_override():
    closes = {"INE000000001": {"price": Decimal("10.50"), "trade_date": date(2026, 1, 1)}}
    rows = rows_for_held(closes, {"INE000000001": 1}, date(2025, 11, 28))
    assert rows[0]["trade_date"] == date(2025, 11, 28)


def test_split_by_source_nse_first_then_bse_remainder():
    needed = {"A": 1, "B": 2, "C": 3}
    found, missing = split_by_source(needed, {"A": {}, "C": {}})
    assert found == {"A": 1, "C": 3}
    assert missing == {"B": 2}

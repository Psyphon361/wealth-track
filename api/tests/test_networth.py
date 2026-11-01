from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services import networth, valuation
from tests.conftest import make_bond, make_cash, make_fd, make_gold, make_stock

TODAY = date(2026, 10, 31)


def make_mf(**kw):
    fields = dict(
        id=1, scheme_code=100, units=Decimal("10"), invested_amount=Decimal("1000"),
        purchase_date=date(2026, 1, 1),
    )  # fmt: skip
    fields.update(kw)
    return SimpleNamespace(**fields)


def txn(day, kind, units, amount):
    return SimpleNamespace(
        txn_date=day, kind=kind, units=Decimal(units), amount=Decimal(amount)
    )


def history(range_key="1y", *, today=TODAY, navs=None, closes=None, txns=None, **holdings):
    return networth.build_history(
        range_key, today, holdings, navs or {}, closes or {}, txns or {},
        (Decimal("0"), Decimal("0")),
    )  # fmt: skip


def point(result, day):
    return next(p for p in result["points"] if p["date"] == day)


def test_fd_point_equals_value_fd_at_that_date():
    fd = make_fd(start_date=date(2025, 12, 1))
    result = history(fd=[fd])
    expected = valuation.value_fd(fd, date(2026, 5, 15))
    p = point(result, "2026-05-15")
    assert p["invested"] == expected["invested"]
    assert p["current"] == expected["current_value"]


def test_holding_excluded_before_start_and_after_maturity():
    bond = make_bond(purchase_date=date(2026, 6, 1), maturity_date=date(2026, 9, 1))
    result = history(bond=[bond])
    assert point(result, "2026-05-31")["invested"] == Decimal("0.00")
    assert point(result, "2026-06-01")["invested"] == Decimal("10000.00")
    assert point(result, "2026-08-31")["invested"] == Decimal("10000.00")
    assert point(result, "2026-09-01")["invested"] == Decimal("0.00")
    assert point(result, "2026-09-01")["current"] == Decimal("0.00")


def test_mf_txn_units_and_fifo_cost_between_txns():
    mf = make_mf(units=Decimal("15"), invested_amount=Decimal("1650"))
    txns = [
        txn(date(2026, 2, 1), "purchase", "10", "1000"),
        txn(date(2026, 4, 1), "purchase", "10", "1200"),
        txn(date(2026, 6, 1), "redemption", "5", "700"),
    ]
    navs = {100: [(date(2026, 1, 1), Decimal("100")), (date(2026, 5, 1), Decimal("110"))]}
    result = history(mf=[mf], navs=navs, txns={1: txns})
    assert point(result, "2026-01-31")["invested"] == Decimal("0.00")
    p = point(result, "2026-05-15")  # 20 units, cost 2200, NAV 110
    assert p["invested"] == Decimal("2200.00")
    assert p["current"] == Decimal("2200.00")
    p = point(result, "2026-07-01")  # redeemed 5 from the first lot: 5 x 100 + 1200
    assert p["invested"] == Decimal("1700.00")
    assert p["current"] == Decimal("1650.00")
    assert point(result, "2026-03-01")["invested"] == Decimal("1000.00")


def test_mf_falls_back_to_constant_units_when_txns_do_not_net():
    mf = make_mf(units=Decimal("10"), invested_amount=Decimal("1000"))
    txns = [txn(date(2026, 2, 1), "purchase", "4", "400")]
    navs = {100: [(date(2025, 12, 1), Decimal("120"))]}
    result = history(mf=[mf], navs=navs, txns={1: txns})
    assert networth.txns_match(mf, txns) is False
    assert point(result, "2026-01-01")["invested"] == Decimal("1000.00")
    assert point(result, "2026-01-01")["current"] == Decimal("1200.00")
    assert point(result, "2025-12-31")["invested"] == Decimal("0.00")


def test_stock_at_cost_before_first_close_then_priced():
    stock = make_stock(
        master_id=7, quantity=10, avg_buy_price=Decimal("100"), buy_date=date(2026, 1, 1)
    )
    closes = {7: [(date(2026, 6, 1), Decimal("150"))]}
    result = history(stock=[stock], closes=closes)
    assert point(result, "2026-05-31")["current"] == Decimal("1000.00")
    assert point(result, "2026-06-01")["current"] == Decimal("1500.00")
    assert point(result, "2026-06-02")["invested"] == Decimal("1000.00")


def test_stocks_at_cost_before_computed():
    stock = make_stock(master_id=7, buy_date=date(2026, 1, 1))
    closes = {7: [(date(2026, 6, 1), Decimal("150"))]}
    result = history(stock=[stock], closes=closes)
    assert result["stocks_at_cost_before"] == "2026-06-01"
    priced = history(stock=[stock], closes={7: [(date(2025, 12, 1), Decimal("90"))]})
    assert priced["stocks_at_cost_before"] is None


def test_no_holdings_gives_empty_series():
    result = history()
    assert result == {"range": "1y", "points": [], "stocks_at_cost_before": None}


def test_today_point_uses_dashboard_totals():
    fd = make_fd(start_date=date(2026, 1, 1))
    result = networth.build_history(
        "1m", TODAY, {"fd": [fd]}, {}, {}, {}, (Decimal("123.456"), Decimal("200"))
    )
    assert result["points"][-1] == {"date": "2026-10-31", "invested": Decimal("123.46"), "current": Decimal("200.00")}


def test_all_range_is_weekly_and_includes_today():
    days = networth.date_list("all", TODAY, date(2026, 8, 1))
    assert days[-1] == TODAY
    assert all((b - a).days == 7 for a, b in zip(days, days[1:]))
    assert days[0] >= date(2026, 8, 1)
    assert (days[0] - date(2026, 8, 1)).days < 7


def test_fixed_ranges_are_daily():
    days = networth.date_list("1m", TODAY, None)
    assert days[0] == date(2026, 9, 30)
    assert days[-1] == TODAY
    assert len(days) == 32


def test_gold_rate_on_or_before_cost_before_first_rate_and_excluded_before_purchase():
    gold = make_gold(purchase_date=date(2026, 10, 1), weight_grams=Decimal("10"),
                     invested_amount=Decimal("50000"), purity="916")
    rates = {("gold", "916"): [(date(2026, 10, 10), Decimal("5100")), (date(2026, 10, 20), Decimal("5200"))]}
    result = networth.build_history(
        "1m", TODAY, {"gold": [gold]}, {}, {}, {}, (Decimal("0"), Decimal("0")), rates
    )
    assert point(result, "2026-09-30")["invested"] == Decimal("0.00")
    p = point(result, "2026-10-05")  # before the first stored rate: valued at cost
    assert p["invested"] == Decimal("50000.00") and p["current"] == Decimal("50000.00")
    assert point(result, "2026-10-15")["current"] == Decimal("51000.00")  # rate of the 10th
    assert point(result, "2026-10-25")["current"] == Decimal("52000.00")  # rate of the 20th


def test_cash_included_from_balance_date_at_balance():
    cash = make_cash(balance_date=date(2026, 10, 10), balance=Decimal("20000"))
    result = networth.build_history(
        "1m", TODAY, {"cash": [cash]}, {}, {}, {}, (Decimal("0"), Decimal("0"))
    )
    assert point(result, "2026-10-09")["invested"] == Decimal("0.00")
    p = point(result, "2026-10-10")
    assert p["invested"] == Decimal("20000.00") and p["current"] == Decimal("20000.00")
    assert point(result, "2026-10-20")["current"] == Decimal("20000.00")

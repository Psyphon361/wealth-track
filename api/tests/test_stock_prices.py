from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

from app.services import stock_master, stock_prices
from app.services.stock_prices import day_change_pct
from app.services.valuation import value_stock
from tests.market_helpers import read


def test_day_change_pct():
    assert day_change_pct(Decimal("110"), Decimal("100")) == Decimal("10.00")
    assert day_change_pct(Decimal("99.5"), Decimal("101")) == Decimal("-1.49")
    assert day_change_pct(Decimal("10"), None) is None
    assert day_change_pct(None, Decimal("10")) is None
    assert day_change_pct(Decimal("10"), Decimal("0")) is None


def test_value_stock_without_price_uses_invested():
    stock = SimpleNamespace(quantity=10, avg_buy_price=Decimal("100.00"))
    out = value_stock(stock)
    assert out["invested"] == out["current_value"] == Decimal("1000.00")
    assert out["gain"] == Decimal("0.00")


def test_value_stock_with_price_uses_quantity_times_price():
    stock = SimpleNamespace(quantity=10, avg_buy_price=Decimal("100.00"))
    out = value_stock(stock, date(2026, 10, 30), price=Decimal("112.50"))
    assert out["current_value"] == Decimal("1125.00")
    assert out["gain"] == Decimal("125.00")
    assert out["gain_pct"] == Decimal("12.50")


def test_parse_closes_reads_all_series_with_trade_date():
    closes = stock_master.parse_closes(read("bse_bhav_sample.csv"), date(2026, 1, 1))
    abb = closes["INE117A01022"]
    assert abb["price"] == Decimal("6140.00")
    assert abb["prev_close"] == Decimal("6460.00")
    assert abb["trade_date"] == date(2026, 10, 23)


def test_parse_closes_nse_sme_sample_and_bad_rows():
    text = read("nse_bhav_sample.csv")
    closes = stock_master.parse_closes(text, date(2026, 1, 1))
    assert closes["INE1GYP01013"]["price"] == Decimal("63.80")
    header = text.splitlines()[0]
    bad = header + "\n2026-10-23,,CM,NSE,STK,1,NOTANISIN,X,EQ,,,,,X,1,1,1,5,1,1,,1,,,1,1,1,F1,1,,,,,\n"
    assert stock_master.parse_closes(bad, date(2026, 1, 1)) == {}


def test_close_time_is_1530_ist():
    assert stock_prices.close_time(date(2026, 10, 23)) == datetime(2026, 10, 23, 10, 0, tzinfo=UTC)

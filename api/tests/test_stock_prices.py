from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.services import stock_master, stock_prices
from app.services.stock_prices import day_change_pct, is_stale, parse_yahoo_chart, yahoo_symbol
from app.services.valuation import value_stock
from tests.market_helpers import read

IST = ZoneInfo("Asia/Kolkata")


def ist(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=IST)


def chart(**meta):
    return {"chart": {"result": [{"meta": meta}], "error": None}}


def test_parse_yahoo_chart_full_meta():
    quote = parse_yahoo_chart(
        chart(regularMarketPrice=812.345, previousClose=800, regularMarketTime=1761820200)
    )
    assert quote.price == Decimal("812.35")
    assert quote.prev_close == Decimal("800.00")
    assert quote.price_time == datetime.fromtimestamp(1761820200, UTC)
    assert quote.price_time.utcoffset() == timedelta(0)


def test_parse_yahoo_chart_falls_back_to_chart_previous_close():
    quote = parse_yahoo_chart(chart(regularMarketPrice=10, chartPreviousClose=9.5))
    assert quote.prev_close == Decimal("9.50")
    assert quote.price_time is None


def test_parse_yahoo_chart_missing_optional_fields():
    quote = parse_yahoo_chart(chart(regularMarketPrice=10))
    assert (quote.prev_close, quote.price_time) == (None, None)


@pytest.mark.parametrize(
    "payload",
    [
        chart(previousClose=9),
        chart(regularMarketPrice=None),
        chart(regularMarketPrice=0),
        {"chart": {"result": None, "error": {"code": "Not Found"}}},
        {"chart": {"result": []}},
        {},
        None,
    ],
)
def test_parse_yahoo_chart_without_price_is_none(payload):
    assert parse_yahoo_chart(payload) is None


@pytest.mark.parametrize(
    ("nse", "bse", "expected"),
    [("PINELABS", "PINELABS", "PINELABS.NS"), (None, "RELIANCE", "RELIANCE.BO"), (None, None, None)],
)
def test_yahoo_symbol(nse, bse, expected):
    assert yahoo_symbol(SimpleNamespace(nse_symbol=nse, bse_symbol=bse)) == expected


def test_stale_when_no_row():
    assert is_stale(None, ist(2026, 10, 28, 11, 0))


def test_in_hours_fresh_within_15_minutes():
    now = ist(2026, 10, 28, 11, 0)  # Wednesday
    assert not is_stale(now - timedelta(minutes=14), now)


def test_in_hours_stale_after_15_minutes():
    now = ist(2026, 10, 28, 11, 0)
    assert is_stale(now - timedelta(minutes=16), now)


def test_in_hours_stale_with_yesterdays_fetch():
    now = ist(2026, 10, 28, 9, 20)
    assert is_stale(ist(2026, 10, 27, 16, 0), now)


def test_after_close_pre_close_fetch_is_stale():
    now = ist(2026, 10, 28, 18, 0)
    assert is_stale(ist(2026, 10, 28, 15, 0), now)


def test_after_close_post_close_fetch_is_fresh():
    now = ist(2026, 10, 28, 18, 0)
    assert not is_stale(ist(2026, 10, 28, 15, 45), now)


def test_before_open_uses_previous_session_close():
    now = ist(2026, 10, 28, 8, 0)
    assert not is_stale(ist(2026, 10, 27, 16, 0), now)
    assert is_stale(ist(2026, 10, 27, 14, 0), now)


def test_weekend_fresh_after_friday_close_stale_before():
    saturday = ist(2026, 10, 31, 12, 0)
    assert not is_stale(ist(2026, 10, 30, 16, 0), saturday)
    assert is_stale(ist(2026, 10, 30, 15, 0), saturday)
    assert not is_stale(ist(2026, 10, 31, 10, 0), ist(2026, 11, 1, 12, 0))


def test_monday_before_open_uses_friday_close():
    monday = ist(2026, 11, 2, 7, 0)
    assert not is_stale(ist(2026, 10, 30, 16, 0), monday)


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


def test_ensure_fresh_skips_fetch_when_all_prices_fresh():
    now = ist(2026, 10, 28, 11, 0)
    row = SimpleNamespace(
        master_id=1, price=Decimal("1"), fetched_at=now - timedelta(minutes=1), last_attempt_at=None
    )
    calls = []
    stock_prices.ensure_fresh(
        RecordingSession(rows=[row]), [1], fetch=lambda s: calls.append(s), now=now
    )
    assert calls == []


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


class RecordingSession:
    """Session double: serves price rows and masters, remembers writes."""

    def __init__(self, rows=(), masters=(), blocked_until=None):
        self.rows = list(rows)
        self.masters = list(masters)
        self.state = (
            SimpleNamespace(value=blocked_until.isoformat()) if blocked_until else None
        )
        self.writes = []
        self.commits = 0

    def get(self, _model, _key):
        return self.state

    def scalars(self, stmt):
        items = self.masters if "stock_master" in str(stmt).split("WHERE")[0] else self.rows
        return SimpleNamespace(all=lambda: items)

    def execute(self, stmt):
        self.writes.append(stmt)

    def commit(self):
        self.commits += 1

    def written(self, table):
        return [w for w in self.writes if table in str(w)]


def master(mid, symbol):
    return SimpleNamespace(id=mid, nse_symbol=symbol, bse_symbol=None)


NOW = ist(2026, 10, 28, 11, 0)


def test_failed_attempt_makes_row_fresh_for_15_minutes():
    attempt = NOW - timedelta(minutes=10)
    old_fetch = NOW - timedelta(hours=3)
    assert is_stale(old_fetch, NOW)
    assert not is_stale(old_fetch, NOW, attempt)
    assert is_stale(old_fetch, NOW, NOW - timedelta(minutes=16))
    assert is_stale(None, NOW, NOW - timedelta(minutes=16))
    assert not is_stale(None, NOW, attempt)


def test_bhavcopy_only_row_is_stale_in_hours_and_after_close():
    just_imported = NOW - timedelta(minutes=5)
    assert is_stale(just_imported, NOW, None, "bhavcopy")
    after_close = ist(2026, 10, 28, 18, 0)
    assert is_stale(ist(2026, 10, 28, 16, 0), after_close, None, "bhavcopy")


def test_recent_yahoo_fetch_is_fresh():
    assert not is_stale(NOW - timedelta(minutes=5), NOW, None, "yahoo")


def test_failed_attempt_on_bhavcopy_row_is_fresh():
    attempt = NOW - timedelta(minutes=5)
    assert not is_stale(NOW - timedelta(minutes=1), NOW, attempt, "bhavcopy")


def test_failed_fetch_records_attempt_without_touching_price():
    session = RecordingSession(masters=[master(1, "AAA")])

    def fail(_symbol):
        raise OSError("down")

    stock_prices.ensure_fresh(session, [1], fetch=fail, now=NOW)
    writes = session.written("stock_price_latest")
    assert len(writes) == 1
    sql = str(writes[0])
    assert "last_attempt_at" in sql and "SET last_attempt_at" in sql
    assert "price=" not in sql.split("DO UPDATE")[1].replace(" ", "")


def test_recent_attempt_row_is_not_fetched_again():
    row = SimpleNamespace(
        master_id=1, price=None, fetched_at=NOW - timedelta(hours=3),
        last_attempt_at=NOW - timedelta(minutes=5),
    )
    calls = []
    stock_prices.ensure_fresh(
        RecordingSession(rows=[row], masters=[master(1, "AAA")]),
        [1], fetch=lambda s: calls.append(s), now=NOW,
    )
    assert calls == []


def test_429_stops_batch_and_sets_cooldown():
    import urllib.error

    masters = [master(i, f"S{i}") for i in range(1, 30)]
    session = RecordingSession(masters=masters)
    calls = []

    def blocked(symbol):
        calls.append(symbol)
        raise urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)

    stock_prices.ensure_fresh(session, [m.id for m in masters], fetch=blocked, now=NOW)
    assert len(calls) < len(masters)  # later requests were skipped
    state_writes = session.written("app_state")
    assert len(state_writes) == 1
    assert (NOW + stock_prices.BLOCK_FOR).isoformat() in state_writes[0].compile().params.values()
    assert session.written("stock_price_latest") == []


def test_cooldown_is_respected_and_expires():
    calls = []
    active = RecordingSession(masters=[master(1, "AAA")], blocked_until=NOW + timedelta(minutes=5))
    stock_prices.ensure_fresh(active, [1], fetch=lambda s: calls.append(s), now=NOW)
    assert calls == []
    expired = RecordingSession(masters=[master(1, "AAA")], blocked_until=NOW - timedelta(minutes=1))
    stock_prices.ensure_fresh(expired, [1], fetch=lambda s: calls.append(s) or None, now=NOW)
    assert calls == ["AAA.NS"]

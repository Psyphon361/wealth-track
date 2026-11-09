"""The frozen clock: dashboard and portfolio values depend on harness.today only, never on the wall clock.

A small world (an FD, a stock with a price, a gold holding with a rate) is read twice with the real
clock patched to two days one year apart; the answers must be identical. A control shows that the
test can see the clock: when the modules read a (shifted) wall-clock date instead of harness.today,
the values change.
"""

import importlib
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from tests.stateful.world import FROZEN_DATE_MODULES, make_frozen_date, sqlite_harness

DAY = date(2026, 6, 15)

FD = {
    "bank": "Clock Bank", "principal": "100000.00", "rate": 7, "start_date": "2026-01-01",
    "compounding": "quarterly", "payout_type": "cumulative", "tenure_years": 5,
}  # fmt: skip
GOLD = {
    "name": "Clock Gold", "form": "coin", "metal": "gold", "purity": "999",
    "weight_grams": "10.000", "purchase_date": "2026-01-01", "invested_amount": "60000.00",
}  # fmt: skip


@pytest.fixture
def world(auth_settings, monkeypatch):
    with sqlite_harness(monkeypatch) as harness:
        harness.reset()
        harness.today = DAY
        yield harness


def seed_market(h) -> int:
    from app.models import GoldRateHistory, GoldRateLatest, StockMaster, StockPriceLatest

    with h.factory() as session:
        master = StockMaster(isin="INE000CLOCK1", kind="stock", name="Clock Ltd", nse_symbol="CLOCK")
        session.add(master)
        session.flush()
        session.add(
            StockPriceLatest(
                master_id=master.id, price=Decimal("125.50"), prev_close=Decimal("124.00"),
                price_time=datetime(2026, 6, 12, 10, 0, tzinfo=timezone.utc), source="bhavcopy",
            )
        )  # fmt: skip
        for day in (date(2026, 6, 11), date(2026, 6, 12)):
            session.add(GoldRateHistory(metal="gold", purity="999", rate_date=day, rate_per_gram=Decimal("7300.00")))
        session.add(
            GoldRateLatest(
                metal="gold", purity="999", rate_per_gram=Decimal("7300.00"),
                rate_date=date(2026, 6, 12), session="PM", source="ibja",
            )
        )  # fmt: skip
        session.commit()
        return master.id


def build_world(h) -> None:
    master_id = seed_market(h)
    stock = {
        "master_id": master_id, "name": "Clock Ltd", "exchange": "NSE", "quantity": 10,
        "avg_buy_price": "100.00", "buy_date": "2026-01-01",
    }  # fmt: skip
    for slug, body in (("fd", FD), ("stock", stock), ("gold", GOLD)):
        response = h.call("POST", f"/api/assets/{slug}", json=body)
        assert response.status_code in (200, 201), response.text


def read(h) -> dict:
    out = {}
    for url in ("/api/dashboard", "/api/portfolio"):
        response = h.call("GET", url)
        assert response.status_code == 200, response.text
        out[url] = response.json()
    return out


def shift_real_clock(monkeypatch, delta: timedelta) -> None:
    """Move the wall clock: time.time and every `datetime` name the app modules hold."""
    real_now = datetime.now(timezone.utc)

    class ShiftedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            moved = real_now + delta
            return moved.astimezone(tz) if tz else moved.replace(tzinfo=None)

        @classmethod
        def utcnow(cls):
            return (real_now + delta).replace(tzinfo=None)

    real_time = time.time()
    monkeypatch.setattr(time, "time", lambda: real_time + delta.total_seconds())
    for name in FROZEN_DATE_MODULES + ("app.services.sip", "app.services.fundings", "app.services.auth"):
        module = importlib.import_module(name)
        if hasattr(module, "datetime"):
            monkeypatch.setattr(module, "datetime", ShiftedDatetime)


def test_values_do_not_depend_on_the_wall_clock(world, monkeypatch):
    build_world(world)
    baseline = read(world)
    # the world is not empty: the FD accrues, the stock and the gold are priced
    assert Decimal(str(baseline["/api/dashboard"]["total_current"])) > Decimal("170000")

    answers = []
    for years in (-1, 1):
        with monkeypatch.context() as m:
            shift_real_clock(m, timedelta(days=365 * years))
            answers.append(read(world))
    assert answers[0] == answers[1] == baseline


def test_values_follow_the_harness_date(world):
    build_world(world)
    before = read(world)["/api/dashboard"]["total_current"]
    world.today = DAY + timedelta(days=120)
    after = read(world)["/api/dashboard"]["total_current"]
    assert after > before  # the FD keeps accruing as the frozen day moves


def test_control_a_real_clock_read_would_change_values(world, monkeypatch):
    """Not frozen (modules read a shifted wall-clock date): the FD value moves, so the test above
    really does prove independence."""
    build_world(world)
    frozen = read(world)["/api/dashboard"]["total_current"]

    def shifted(years: int):
        class Wall:  # stands in for the harness: "today" is the wall clock, shifted
            today = date.today() + timedelta(days=365 * years)

        return make_frozen_date(Wall)

    values = []
    for years in (-1, 1):
        with monkeypatch.context() as m:
            for name in FROZEN_DATE_MODULES:
                m.setattr(importlib.import_module(name), "date", shifted(years))
            values.append(read(world)["/api/dashboard"]["total_current"])
    assert values[0] != values[1]
    assert frozen not in values

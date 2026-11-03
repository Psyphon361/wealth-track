"""Benchmark history freshness (request path never refetches stale data; cron tops it up) and
the single-query NPS start NAV lookup."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.routers import analytics_returns as router
from app.services import analytics_benchmark as ab
from app.services import nav_history


class FakeSession:
    def __init__(self, sync=None, rows=None, held=()):
        self.sync, self.rows, self.held = sync, rows or [], held
        self.statements = []
        self.rolled_back = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, model, key):
        return self.sync

    def rollback(self):
        self.rolled_back = True

    def scalars(self, stmt):
        return list(self.held)

    def execute(self, stmt):
        self.statements.append(stmt)
        return _Rows(self.rows)


class _Rows(list):
    def all(self):
        return list(self)


def _sync(age_hours):
    return SimpleNamespace(fetched_at=datetime.now(timezone.utc) - timedelta(hours=age_hours))


def _patch_session(monkeypatch, fake):
    monkeypatch.setattr(router, "Session", lambda *a, **k: fake)


def test_request_does_not_fetch_when_history_exists_even_if_stale(monkeypatch):
    calls = []
    monkeypatch.setattr(router, "resolve_nav", lambda *a: calls.append(a))
    _patch_session(monkeypatch, FakeSession(sync=_sync(72)))
    router._refresh_benchmark_history(object(), object())
    assert calls == []


def test_request_fetches_when_no_history(monkeypatch):
    calls = []
    monkeypatch.setattr(router, "resolve_nav", lambda *a: calls.append(a))
    _patch_session(monkeypatch, FakeSession(sync=None))
    router._refresh_benchmark_history(object(), object())
    assert len(calls) == 1 and calls[0][1] == nav_history.BENCHMARK_SCHEME_CODE


def test_cron_refreshes_stale_benchmark(monkeypatch):
    stored = []
    monkeypatch.setattr(ab, "fetch_mfapi", lambda code: [("row",)])
    monkeypatch.setattr(ab, "store_history", lambda *a: stored.append(a))
    assert ab.refresh_benchmark_history(FakeSession(sync=_sync(30))) is True
    assert ab.refresh_benchmark_history(FakeSession(sync=None)) is True
    assert ab.refresh_benchmark_history(FakeSession(sync=_sync(1))) is False
    assert [s[1] for s in stored] == [nav_history.BENCHMARK_SCHEME_CODE] * 2


def test_cron_refresh_swallows_fetch_failure(monkeypatch):
    def boom(code):
        raise RuntimeError("down")

    monkeypatch.setattr(ab, "fetch_mfapi", boom)
    fake = FakeSession(sync=None)
    assert ab.refresh_benchmark_history(fake) is False and fake.rolled_back


def test_daily_append_counts_benchmark_as_held():
    code = nav_history.BENCHMARK_SCHEME_CODE
    day = datetime(2026, 11, 3).date()
    fake = FakeSession(held=[], rows=[(code,)])
    n = nav_history.append_today_for_holdings(
        fake, [(code, day, Decimal("10")), (999, day, Decimal("5"))]
    )
    assert n == 1
    insert = fake.statements[0]
    assert len(insert._multi_values[0]) == 1  # only the benchmark row, not scheme 999


def _nps_groups():
    def item(id_, scheme, start, status="active"):
        return {"id": id_, "scheme_id": scheme, "start_date": start, "status": status}

    return [
        {"type": "nps", "items": [item(1, 10, "2025-01-01"), item(2, 11, "2025-02-01"),
                                  item(3, 12, "2025-03-01"), item(4, 10, "2025-01-01", "closed")]},
        {"type": "fd", "items": [item(9, 1, "2025-01-01")]},
    ]


def test_nps_start_navs_single_query_maps_found_and_skips_missing(monkeypatch):
    # Holding 3 has no NAV in the window, so the lateral join yields no row for it.
    from datetime import date

    def nav(scheme, d, v):
        return SimpleNamespace(scheme_id=scheme, nav_date=d, nav=Decimal(v))

    fake = FakeSession(rows=[
        nav(10, date(2024, 12, 30), "30.0"), nav(10, date(2025, 1, 1), "30.5"),
        nav(10, date(2025, 1, 2), "99"),  # after the start: ignored
        nav(11, date(2025, 1, 20), "31.25"),  # 12 days before start: outside window
        nav(11, date(2025, 1, 29), "31.0"),
        nav(12, date(2024, 1, 1), "5"),  # far outside window
    ])
    _patch_session(monkeypatch, fake)
    out = router._fetch_nps_start_navs(object(), _nps_groups())
    assert out == {1: Decimal("30.5"), 2: Decimal("31.0")}
    assert len(fake.statements) == 1


def test_nps_start_navs_no_active_holdings_runs_no_query(monkeypatch):
    fake = FakeSession()
    _patch_session(monkeypatch, fake)
    assert router._fetch_nps_start_navs(object(), [{"type": "fd", "items": []}]) == {}
    assert fake.statements == []

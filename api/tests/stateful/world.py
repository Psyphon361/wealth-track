"""World for the stateful money tests: a test database, the app wired to it, HTTP and typed reads.

Safety (this module must never reach Neon or any real database):
  * Settings reads api/.env (a Neon dev URL) when app.config is imported. Nothing here uses it: the
    app is pointed at the test engine by assigning `app.db._engine` and rebinding
    `app.db.SessionLocal`, exactly like the pg harness (`pg_app`), and both are restored afterwards.
  * `sqlite_harness` installs the same socket guard as the pg harness (no connection to a non-local
    address; this also stops mfapi.in and other outbound HTTP).
  * `Harness.assert_safe()` runs before every Hypothesis run and at the start of every example: the
    engine must be an in-memory SQLite engine, or a local `wt_test_*` Postgres database, and it must
    be the engine the app uses.

Network and clocks: `today_ist` is patched to `harness.today` (a fixed day the machine can advance)
and `ensure_history` is a no-op; MF scheme 100 and a daily NAV history (seeded once) cover every due
date, so no NAV is ever fetched. Valuation, net worth, portfolio, analytics and the other readers
take their `date` from `FROZEN_DATE_MODULES`, whose `date.today()` is `harness.today` too, so the
real wall clock affects no value. Market data (a stock price, the MF latest NAV, a gold or silver
rate; latest and history rows) exists only after the machine's market rules ran, dated from
`harness.today`; until then holdings are valued at invested. Two stock masters are seeded once
(`harness.stock_masters`) so stocks can be linked to a price.

The database is reused across Hypothesis examples. `reset()` deletes the holding data in reverse
`sorted_tables` order; users, the MF master and the NAV history stay (the user is created ONCE:
argon2 runs on sign-up and must not run per example).
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, delete, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

START_TODAY = date(2026, 3, 10)  # the machine's first "today"
LAST_TODAY = date(2026, 7, 20)  # NAV history is seeded to 2026-07-31
SCHEME = 100

RESET_TABLES = (
    "holding_fundings", "holding_exits", "mf_sip_skips", "mf_sips", "mf_transactions",
    "fixed_deposits", "recurring_deposits", "stocks", "bonds", "mutual_funds", "nps_holdings",
    "gold_holdings", "cash_holdings", "pf_holdings", "other_holdings",
    # market data written by the machine's market rules (masters and the NAV history stay)
    "stock_price_latest", "stock_price_history", "mf_nav_latest", "gold_rate_latest", "gold_rate_history",
)  # fmt: skip

CRON_SECRET = "stateful-cron-secret"

CENT = Decimal("0.01")
MILLI = Decimal("0.001")


# --- money helpers (built from integers; sent as strings) -------------------------------------


def d(value: Any) -> Decimal:
    return Decimal(str(value))


def q2(value: Any) -> Decimal:
    return d(value).quantize(CENT, rounding=ROUND_HALF_UP)


def q3(value: Any) -> Decimal:
    return d(value).quantize(MILLI, rounding=ROUND_HALF_UP)


def from_cents(cents: int) -> Decimal:
    return Decimal(cents).scaleb(-2)


def from_milli(milli: int) -> Decimal:
    return Decimal(milli).scaleb(-3)


def sx(value: Decimal) -> str:
    return format(value, "f")


def reason(response) -> str:
    """The message of an error response (validation messages are in detail[0].msg)."""
    body = response.json()
    detail = body.get("detail")
    if isinstance(detail, list) and detail and isinstance(detail[0], dict):
        return str(detail[0].get("msg", ""))
    return str(body.get("message", ""))


class ServerError(AssertionError):
    """A 5xx or an exception out of the app."""


# --- the harness -----------------------------------------------------------------------------


class Harness:
    """Engine, session factory, authenticated client and typed reads for one pytest test."""

    def __init__(
        self, engine: Engine, factory: sessionmaker, user: Any, *, local_pg: bool, user2: Any = None
    ) -> None:
        from app.services.auth import create_access_token

        self.engine = engine
        self.factory = factory
        self.user = user
        self.user2 = user2  # the second user: owns a few holdings, tries user 1's ids
        self.uid = user.id
        self.uid2 = user2.id if user2 is not None else None
        self.local_pg = local_pg
        self.fk = local_pg  # foreign-key actions (CASCADE, SET NULL) are enforced by the database
        self.today = START_TODAY
        self.log: list[str] = []
        self.stock_masters: list[int] = []  # ids of the seeded stock masters
        self._issue = create_access_token
        self._token_at = 0.0
        self.headers: dict[str, str] = {}
        self.headers2: dict[str, str] = {}
        self._refresh_token()

    # safety --------------------------------------------------------------------------------
    def assert_safe(self) -> None:
        from app import db

        url = make_url(str(self.engine.url))
        if url.drivername.startswith("sqlite"):
            assert url.database in (None, "", ":memory:"), f"unexpected SQLite file {url.database}"
        else:
            assert self.local_pg, f"unexpected database driver {url.drivername}"
            assert url.host in ("localhost", "127.0.0.1", "::1") or (url.host or "").startswith("/")
            assert (url.database or "").startswith("wt_test_"), f"not a test database: {url.database}"
        assert db._engine is self.engine, "the app is not using the test engine"
        assert db.SessionLocal.kw.get("bind") is self.engine, "SessionLocal is not on the test engine"

    # requests ------------------------------------------------------------------------------
    def _refresh_token(self) -> None:
        token, _ = self._issue(self.user)
        self.headers = {"Authorization": f"Bearer {token}"}
        if self.user2 is not None:
            token2, _ = self._issue(self.user2)
            self.headers2 = {"Authorization": f"Bearer {token2}"}
        self._token_at = time.monotonic()

    def call(self, method: str, url: str, *, as_user: int = 1, **kwargs):
        """One request (as user 1, or as the second user with as_user=2). A 5xx or an exception
        fails with the operation log."""
        from app.main import app

        if time.monotonic() - self._token_at > 600:
            self._refresh_token()
        who = "" if as_user == 1 else f"[user {as_user}] "
        self.log.append(f"{who}{method} {url} {kwargs.get('params') or ''} {kwargs.get('json') or ''}")
        headers = self.headers if as_user == 1 else self.headers2
        try:
            response = TestClient(app).request(method, url, headers=headers, **kwargs)
        except Exception as error:  # noqa: BLE001 - TestClient re-raises server errors
            raise ServerError(f"{method} {url} raised {error!r}\n{self.tail()}") from error
        self.log[-1] += f" -> {response.status_code}"
        if response.status_code >= 500:
            raise ServerError(f"{method} {url} -> {response.status_code}\n{self.tail()}")
        return response

    def tail(self, n: int = 14) -> str:
        return "operation log (last %d):\n  " % n + "\n  ".join(self.log[-n:])

    # raw reads (soft-deleted rows included) ----------------------------------------------------
    def rows(self, sql: str, **params) -> list[Any]:
        with self.engine.connect() as conn:
            return list(conn.execute(text(sql), params).all())

    def scalar(self, sql: str, **params) -> Any:
        with self.engine.connect() as conn:
            return conn.execute(text(sql), params).scalar()

    def snapshot(self) -> list[tuple]:
        """Every row of every holding, exit, funding, SIP and transaction table (both users, soft-deleted
        rows included, updated_at included): equal before and after a call means it changed nothing."""
        out = []
        for table in (
            "cash_holdings", "fixed_deposits", "stocks", "bonds", "mutual_funds", "gold_holdings",
            "other_holdings", "holding_exits", "holding_fundings", "mf_sips", "mf_sip_skips", "mf_transactions",
        ):  # fmt: skip
            out.append((table, [tuple(row) for row in self.rows(f"SELECT * FROM {table} ORDER BY id")]))  # noqa: S608
        return out

    # reset ---------------------------------------------------------------------------------
    def reset(self) -> None:
        """Between examples: empty the holding tables (the user and the NAV data stay)."""
        from app.db import Base

        self.assert_safe()
        tables = [t for t in reversed(Base.metadata.sorted_tables) if t.name in RESET_TABLES]
        with self.engine.begin() as conn:
            for table in tables:
                conn.execute(delete(table))
        self.today = START_TODAY
        self.log.clear()

    # SIP posting with the test session factory (the nightly job path) ----------------------------
    def post_due(self) -> dict[int, int]:
        from app.services import sip as sip_service

        self.assert_safe()
        with self.factory() as session:
            return sip_service.post_due(session, self.today)

    # purge and the retention clock ---------------------------------------------------------------
    def backdate_deleted(self, table: str, row_id: int, age_days: int) -> None:
        """Make a soft-deleted row look `age_days` old to the purge, which measures age against the real
        wall clock (datetime.now in services/purge.py; app code is not patched). The stamp is one hour
        later than exactly `age_days` ago, so an age of exactly 30 days is NOT past retention and 31 is,
        however long the test takes."""
        from sqlalchemy import update

        from app.db import Base

        self.assert_safe()
        stamp = datetime.now(timezone.utc) - timedelta(days=age_days) + timedelta(hours=1)
        tbl = Base.metadata.tables[table]
        with self.engine.begin() as conn:
            conn.execute(update(tbl).where(tbl.c.id == row_id).values(deleted_at=stamp))

    def purge(self, *, via_cron: bool) -> dict[str, int]:
        """Run the purge: the service function (a session of the test factory) or GET /api/cron/purge
        with the cron secret. On SQLite (foreign keys off) the database's ON DELETE actions are applied
        by hand afterwards, so the rest of the checks see what Postgres would have left."""
        from fastapi.testclient import TestClient

        from app.main import app
        from app.services import purge as purge_service

        self.assert_safe()
        self.log.append(f"purge via {'cron' if via_cron else 'service'}")
        if via_cron:
            response = TestClient(app).get("/api/cron/purge", headers={"Authorization": f"Bearer {CRON_SECRET}"})
            if response.status_code != 200:
                raise ServerError(f"GET /api/cron/purge -> {response.status_code} {response.text[:300]}\n{self.tail()}")
            counts = response.json()
        else:
            with self.factory() as session:
                counts = purge_service.purge_deleted(session)
        if not self.fk:
            with self.engine.begin() as conn:
                for sql in (
                    "DELETE FROM mf_transactions WHERE mutual_fund_id NOT IN (SELECT id FROM mutual_funds)",
                    "UPDATE mf_sips SET mutual_fund_id = NULL WHERE mutual_fund_id IS NOT NULL "
                    "AND mutual_fund_id NOT IN (SELECT id FROM mutual_funds)",
                    "UPDATE holding_exits SET cash_holding_id = NULL WHERE cash_holding_id IS NOT NULL "
                    "AND cash_holding_id NOT IN (SELECT id FROM cash_holdings)",
                    "UPDATE holding_fundings SET cash_holding_id = NULL WHERE cash_holding_id IS NOT NULL "
                    "AND cash_holding_id NOT IN (SELECT id FROM cash_holdings)",
                    "UPDATE holding_fundings SET from_exit_id = NULL WHERE from_exit_id IS NOT NULL "
                    "AND from_exit_id NOT IN (SELECT id FROM holding_exits)",
                ):
                    conn.execute(text(sql))
        return counts

    # market data (latest and history rows, dated from the harness clock) -----------------------
    def nav_on(self, on: date) -> tuple[date, Decimal]:
        """(day, NAV) of the last seeded history row on or before a day (the history is daily, ends
        2026-07-31 and is never changed)."""
        row = self.rows(
            "SELECT nav_date, nav FROM mf_nav_history WHERE scheme_code = :c AND nav_date <= :d "
            "ORDER BY nav_date DESC LIMIT 1", c=SCHEME, d=on,
        )[0]  # fmt: skip
        day = row[0] if isinstance(row[0], date) else date.fromisoformat(str(row[0]))
        return day, d(row[1])

    def set_stock_price(self, master_id: int, price: Decimal, prev_close: Decimal) -> None:
        """Latest price and today's history close, both for harness.today."""
        from app.models import StockPriceHistory, StockPriceLatest

        self.assert_safe()
        with self.factory() as session:
            session.merge(
                StockPriceLatest(
                    master_id=master_id, price=price, prev_close=prev_close, source="bhavcopy",
                    price_time=datetime(self.today.year, self.today.month, self.today.day, 10, 0, tzinfo=timezone.utc),
                )
            )  # fmt: skip
            session.merge(StockPriceHistory(master_id=master_id, trade_date=self.today, close=price))
            session.commit()

    def set_mf_latest_nav(self, nav_date: date) -> Decimal:
        """Latest NAV of SCHEME = the last history NAV on or before nav_date; returns it."""
        from app.models import MFNavLatest

        self.assert_safe()
        nav_date, nav = self.nav_on(nav_date)
        with self.factory() as session:
            session.merge(MFNavLatest(scheme_code=SCHEME, nav=nav, nav_date=nav_date))
            session.commit()
        return nav

    def set_metal_rate(self, metal: str, purity: str, rate: Decimal, rate_date: date) -> None:
        """Latest rate (replaced) and the history row of its date (added)."""
        from app.models import GoldRateHistory, GoldRateLatest

        self.assert_safe()
        with self.factory() as session:
            session.merge(GoldRateHistory(metal=metal, purity=purity, rate_date=rate_date, rate_per_gram=rate))
            session.merge(
                GoldRateLatest(
                    metal=metal, purity=purity, rate_per_gram=rate, rate_date=rate_date,
                    session="PM", source="ibja",
                )
            )  # fmt: skip
            session.commit()


class _FrozenMeta(type(date)):
    def __instancecheck__(cls, obj):
        return isinstance(obj, date)

    def __subclasscheck__(cls, sub):
        return issubclass(sub, date)


def make_frozen_date(harness: Harness):
    """A stand-in for `datetime.date` whose today() is harness.today. Everything else gives real
    dates (constructors return plain `date`, isinstance works for real dates)."""

    class FrozenDate(date, metaclass=_FrozenMeta):
        def __new__(cls, *args, **kwargs):
            return date(*args, **kwargs)

        @classmethod
        def today(cls):
            return harness.today

        @classmethod
        def fromisoformat(cls, value):
            return date.fromisoformat(value)

        @classmethod
        def fromordinal(cls, n):
            return date.fromordinal(n)

    return FrozenDate


# Every module that reads the date for valuation, maturity/status, accrual, the gold rate window,
# net worth history, analytics and the dashboard. (`datetime.now(...)` uses elsewhere only stamp
# rows or fetch limits and do not affect values.)
FROZEN_DATE_MODULES = (
    "app.services.valuation",
    "app.services.cas_import",
    "app.services.nav_history",
    "app.services.gold_history",
    "app.routers.portfolio",
    "app.routers.networth",
    "app.routers.holdings",
    "app.routers.analytics",
    "app.routers.analytics_gains",
    "app.routers.analytics_tax",
    "app.routers.analytics_returns",
)


def patch_clock_and_network(monkeypatch, harness: Harness) -> None:
    """One clock: every date source follows harness.today; no NAV history fetch."""
    import importlib

    from app.services import sip as sip_service

    from app.config import settings

    monkeypatch.setattr(settings, "cron_secret", CRON_SECRET)
    monkeypatch.setattr(sip_service, "today_ist", lambda: harness.today)
    monkeypatch.setattr(sip_service, "ensure_history", lambda session, code: None)
    frozen = make_frozen_date(harness)
    for name in FROZEN_DATE_MODULES:
        module = importlib.import_module(name)
        monkeypatch.setattr(module, "date", frozen)


def seed_funds(factory: sessionmaker) -> None:
    """MF master 100 and a daily NAV history with a fresh sync (so nothing is fetched)."""
    from app.models import MFMaster, MFNavHistory, MFNavHistorySync

    with factory() as session:
        session.add(
            MFMaster(scheme_code=SCHEME, name="Fund A - Direct Growth", category="equity", is_active=True)
        )
        session.flush()
        day = date(2024, 12, 1)
        rows = []
        while day <= date(2026, 7, 31):
            nav = Decimal(40 + (day.toordinal() * 7) % 25)  # varies, so FIFO costs are not trivial
            rows.append(MFNavHistory(scheme_code=SCHEME, nav_date=day, nav=nav))
            day += timedelta(days=1)
        session.add_all(rows)
        session.add(
            MFNavHistorySync(
                scheme_code=SCHEME, first_date=date(2024, 12, 1), last_date=date(2026, 7, 31),
                fetched_at=datetime.now(timezone.utc),
            )
        )  # fmt: skip
        session.commit()


def seed_stock_masters(factory: sessionmaker) -> list[int]:
    """Two listed stocks a holding can be linked to (so a price can apply); kept across examples."""
    from app.models import StockMaster

    with factory() as session:
        masters = [
            StockMaster(isin=f"INE000SM000{i}", kind="stock", name=f"Master Stock {i}", nse_symbol=f"MSTK{i}")
            for i in (1, 2)
        ]
        session.add_all(masters)
        session.commit()
        return [m.id for m in masters]


def _make_user(factory: sessionmaker, email: str):
    from app.models.user import User
    from app.services.auth import hash_password

    with factory() as session:
        user = User(email=email, password_hash=hash_password("Sup3r-secret-pw!"), is_active=True)
        session.add(user)
        session.commit()
        return user


@contextmanager
def sqlite_harness(monkeypatch, *, foreign_keys: bool = False):
    """An in-memory SQLite test database wired into the app, with a user, funds and a socket guard.

    Needs the `auth_settings` fixture (jwt secret) to be active in the calling test.
    """
    from app import db
    from app.db import Base
    from app.models import (
        Bond, Cash, FixedDeposit, Gold, GoldRateHistory, GoldRateLatest, HoldingExit, HoldingFunding, MFMaster,
        MFNavHistory, MFNavHistorySync, MFNavLatest, MFTransaction, MfSip, MfSipSkip, MutualFund,
        Nps, NpsMaster, NpsNavHistory, NpsNavHistorySync, NpsNavLatest, Other, Pf,
        RecurringDeposit, Stock, StockMaster, StockPriceHistory, StockPriceLatest,
    )  # fmt: skip
    from app.models.login_attempt import LoginAttempt
    from app.models.refresh_token import RefreshToken
    from app.models.user import User
    from tests.pg.conftest import _SocketGuard

    guard = _SocketGuard()
    guard.install()
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    if foreign_keys:

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_connection, _record):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

    tables = [User, RefreshToken, LoginAttempt] + [
        FixedDeposit, RecurringDeposit, Stock, Bond, MutualFund, Gold, Cash, Pf, Other,
        GoldRateLatest, GoldRateHistory, StockMaster, StockPriceLatest, StockPriceHistory, MFNavLatest, MFTransaction, MfSip, MfSipSkip, NpsMaster, NpsNavLatest,
        NpsNavHistory, NpsNavHistorySync, Nps, HoldingExit, HoldingFunding, MFMaster,
        MFNavHistory, MFNavHistorySync,
    ]  # fmt: skip
    previous_engine = db._engine
    previous_bind = db.SessionLocal.kw.get("bind")
    try:
        Base.metadata.create_all(engine, tables=[m.__table__ for m in tables])
        db._engine = engine
        db.SessionLocal.configure(bind=engine)
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        user = _make_user(factory, "stateful@example.com")
        user2 = _make_user(factory, "stateful2@example.com")
        seed_funds(factory)
        harness = Harness(engine, factory, user, local_pg=False, user2=user2)
        harness.stock_masters = seed_stock_masters(factory)
        harness.fk = foreign_keys
        harness.assert_safe()
        patch_clock_and_network(monkeypatch, harness)
        yield harness
    finally:
        db._engine = previous_engine
        db.SessionLocal.configure(bind=previous_bind)
        engine.dispose()
        guard.remove()


def pg_harness(pg_app, monkeypatch) -> Harness:
    """The same world on the throwaway local Postgres database of the `pg_app` fixture."""
    harness = Harness(
        pg_app.engine, pg_app.session, _make_user(pg_app.session, "stateful-pg@example.com"),
        local_pg=True, user2=_make_user(pg_app.session, "stateful-pg-2@example.com"),
    )  # fmt: skip
    seed_funds(pg_app.session)
    harness.stock_masters = seed_stock_masters(pg_app.session)
    harness.assert_safe()
    patch_clock_and_network(monkeypatch, harness)
    return harness

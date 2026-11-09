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
date, so no NAV is ever fetched. Valuation still uses the wall clock (`date.today()`), so every
maturity used here is well in the past.

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
)  # fmt: skip

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

    def __init__(self, engine: Engine, factory: sessionmaker, user: Any, *, local_pg: bool) -> None:
        from app.services.auth import create_access_token

        self.engine = engine
        self.factory = factory
        self.user = user
        self.local_pg = local_pg
        self.today = START_TODAY
        self.log: list[str] = []
        self._issue = create_access_token
        self._token_at = 0.0
        self.headers: dict[str, str] = {}
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
        self._token_at = time.monotonic()

    def call(self, method: str, url: str, **kwargs):
        """One request. A 5xx or an exception fails with the operation log."""
        from app.main import app

        if time.monotonic() - self._token_at > 600:
            self._refresh_token()
        self.log.append(f"{method} {url} {kwargs.get('params') or ''} {kwargs.get('json') or ''}")
        try:
            response = TestClient(app).request(method, url, headers=self.headers, **kwargs)
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


def patch_clock_and_network(monkeypatch, harness: Harness) -> None:
    """`today_ist` follows harness.today; no NAV history fetch."""
    from app.services import sip as sip_service

    monkeypatch.setattr(sip_service, "today_ist", lambda: harness.today)
    monkeypatch.setattr(sip_service, "ensure_history", lambda session, code: None)


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
        Bond, Cash, FixedDeposit, Gold, GoldRateLatest, HoldingExit, HoldingFunding, MFMaster,
        MFNavHistory, MFNavHistorySync, MFNavLatest, MFTransaction, MfSip, MfSipSkip, MutualFund,
        Nps, NpsMaster, NpsNavHistory, NpsNavHistorySync, NpsNavLatest, Other, Pf,
        RecurringDeposit, Stock,
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
        GoldRateLatest, MFNavLatest, MFTransaction, MfSip, MfSipSkip, NpsMaster, NpsNavLatest,
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
        seed_funds(factory)
        harness = Harness(engine, factory, user, local_pg=False)
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
    harness = Harness(pg_app.engine, pg_app.session, _make_user(pg_app.session, "stateful-pg@example.com"), local_pg=True)
    seed_funds(pg_app.session)
    harness.assert_safe()
    patch_clock_and_network(monkeypatch, harness)
    return harness

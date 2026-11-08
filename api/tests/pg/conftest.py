"""Real-Postgres test harness (marker `pg`).

Running:
  scripts/pg_test_cluster.sh start
  export TEST_DATABASE_URL=$(scripts/pg_test_cluster.sh url)
  .venv/bin/python -m pytest -q -m "not pg"   # the SQLite suite
  .venv/bin/python -m pytest -q -m pg         # these tests
Without TEST_DATABASE_URL the pg tests are SKIPPED and plain `pytest -q` stays DB-free. With the
URL set, pg tests run whenever they are selected (plain `pytest -q` runs them too). CI sets
REQUIRE_PG=1: then a missing URL FAILS the run instead of skipping, so a green gate cannot mean
"nothing ran". CI runs `pytest -q -m "not pg"` first, then `pytest -q -m pg`.

Safety (this harness must never reach Neon or any real database):
  * TEST_DATABASE_URL must point at localhost, 127.0.0.1, ::1 or a unix socket directory.
  * Each session creates its own database `wt_test_<hex>` through that admin connection and drops
    it at the end; every connection to it checks `current_database()` starts with `wt_test_`.
  * A socket guard makes Python-level connections to non-local addresses raise for the session
    (this also stops accidental mfapi.in and other outbound HTTP). libpq (psycopg) does not use
    Python sockets, so the host allowlist above is what protects the database connections.
  * The harness never reads api/.env. app.config.Settings does that itself on import (from the
    cwd); the harness assigns `settings.database_url` directly and asserts its host right before
    running Alembic.
  * `lock_timeout` is set on the TEST engines only, never in app code.

The app under test is pointed at the test database by `pg_app`: it sets `app.db._engine` and
rebinds `app.db.SessionLocal`, then restores both. FastAPI dependency_overrides are not used.
Data is COMMITTED (threads need to see it across connections); `pg_clean` TRUNCATEs every app
table (except alembic_version) before each test that asks for it, so tests seed what they need.
"""

from __future__ import annotations

import os
import secrets
import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

API_DIR = Path(__file__).resolve().parents[2]
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
TEST_DB_PREFIX = "wt_test_"
TEST_LOCK_TIMEOUT_MS = 10_000


# --- URL safety ---------------------------------------------------------------------------------


def _host_is_local(host: str | None) -> bool:
    return bool(host) and (host in LOCAL_HOSTS or host.startswith("/"))


def normalise_url(raw: str) -> URL:
    """The URL in the psycopg 3 form the app uses (`postgresql+psycopg://`)."""
    url = make_url(raw)
    if url.drivername in ("postgresql", "postgres"):
        url = url.set(drivername="postgresql+psycopg")
    return url


def assert_local_url(raw: str | URL) -> URL:
    """Return the parsed URL, or raise RuntimeError unless every host in it is local."""
    url = make_url(raw) if isinstance(raw, str) else raw
    if not url.drivername.startswith("postgres"):
        raise RuntimeError(f"Refusing non-Postgres test database URL (driver {url.drivername!r}).")
    hosts: list[str | None] = [url.host]
    for key in ("host", "hostaddr"):
        value = url.query.get(key)
        if value is not None:
            hosts.extend(value if isinstance(value, tuple) else [value])
    if not any(hosts):
        raise RuntimeError("Refusing test database URL without an explicit local host.")
    for host in hosts:
        if host is None:
            continue
        for part in host.split(","):
            if not _host_is_local(part.strip()):
                raise RuntimeError(
                    f"Refusing non-local test database host {part!r}: only localhost, "
                    "127.0.0.1, ::1 or a unix socket directory are allowed."
                )
    return url


def require_pg_missing_url(env: dict[str, str] | os._Environ) -> bool:
    """True when REQUIRE_PG=1 is set but TEST_DATABASE_URL is not."""
    return env.get("REQUIRE_PG") == "1" and not env.get("TEST_DATABASE_URL")


def assert_test_database(connection) -> None:
    """Raise unless the connection is on a throwaway `wt_test_*` database."""
    name = connection.execute(text("SELECT current_database()")).scalar_one()
    if not str(name).startswith(TEST_DB_PREFIX):
        raise RuntimeError(f"Refusing to use database {name!r}: not a {TEST_DB_PREFIX}* database.")


# --- socket guard -------------------------------------------------------------------------------


def _address_allowed(family: int, address: Any) -> bool:
    if family == getattr(socket, "AF_UNIX", -1):
        return True
    if isinstance(address, tuple) and address:
        return _host_is_local(str(address[0]))
    return False


class _SocketGuard:
    """Makes connects to non-local addresses raise until `remove()` is called."""

    def __init__(self) -> None:
        self._originals: dict[str, Any] = {}

    def install(self) -> None:
        if self._originals:
            return
        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex
        original_getaddrinfo = socket.getaddrinfo
        self._originals = {
            "connect": original_connect,
            "connect_ex": original_connect_ex,
            "getaddrinfo": original_getaddrinfo,
        }

        def connect(sock, address):
            if not _address_allowed(sock.family, address):
                raise RuntimeError(f"socket guard: connection to {address!r} is not allowed")
            return original_connect(sock, address)

        def connect_ex(sock, address):
            if not _address_allowed(sock.family, address):
                raise RuntimeError(f"socket guard: connection to {address!r} is not allowed")
            return original_connect_ex(sock, address)

        def getaddrinfo(host, *args, **kwargs):
            if host is not None and not _host_is_local(str(host)):
                raise RuntimeError(f"socket guard: lookup of {host!r} is not allowed")
            return original_getaddrinfo(host, *args, **kwargs)

        socket.socket.connect = connect
        socket.socket.connect_ex = connect_ex
        socket.getaddrinfo = getaddrinfo

    def remove(self) -> None:
        if not self._originals:
            return
        socket.socket.connect = self._originals["connect"]
        socket.socket.connect_ex = self._originals["connect_ex"]
        socket.getaddrinfo = self._originals["getaddrinfo"]
        self._originals = {}


@pytest.fixture(scope="session", autouse=True)
def pg_socket_guard() -> Iterator[None]:
    guard = _SocketGuard()
    guard.install()
    try:
        yield
    finally:
        guard.remove()


# --- skip / require logic -----------------------------------------------------------------------


def pytest_collection_modifyitems(config, items):
    pg_items = [item for item in items if item.get_closest_marker("pg")]
    if not pg_items:
        return
    if require_pg_missing_url(os.environ):
        raise pytest.UsageError(
            "REQUIRE_PG=1 is set but TEST_DATABASE_URL is missing: the pg tests cannot run. "
            "Start a local cluster (scripts/pg_test_cluster.sh start) or set the URL."
        )
    if not os.environ.get("TEST_DATABASE_URL"):
        skip = pytest.mark.skip(reason="TEST_DATABASE_URL is not set (see tests/pg/conftest.py)")
        for item in pg_items:
            item.add_marker(skip)


# --- engines and databases ----------------------------------------------------------------------


def make_engine(url: URL, *, test_database: bool = True, **kwargs) -> Engine:
    """Engine like the app's (psycopg 3, no prepared statements) with a low lock_timeout."""
    assert_local_url(url)
    options = f"-c lock_timeout={TEST_LOCK_TIMEOUT_MS}" if test_database else ""
    connect_args: dict[str, Any] = {"prepare_threshold": None}
    if options:
        connect_args["options"] = options
    engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True, **kwargs)
    if test_database:

        @event.listens_for(engine, "connect")
        def _check_database(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("SELECT current_database()")
                name = cursor.fetchone()[0]
            finally:
                cursor.close()
            dbapi_connection.rollback()
            if not str(name).startswith(TEST_DB_PREFIX):
                raise RuntimeError(f"Refusing connection to database {name!r}: not wt_test_*.")

    return engine


@pytest.fixture(scope="session")
def pg_admin_url() -> URL:
    raw = os.environ.get("TEST_DATABASE_URL")
    if not raw:
        pytest.skip("TEST_DATABASE_URL is not set")
    return assert_local_url(normalise_url(raw))


@contextmanager
def scratch_database(admin_url: URL) -> Iterator[URL]:
    """Create `wt_test_<hex>` through the admin connection; drop it (FORCE) on exit."""
    assert_local_url(admin_url)
    name = f"{TEST_DB_PREFIX}{secrets.token_hex(6)}"
    admin = make_engine(admin_url, test_database=False, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        yield admin_url.set(database=name)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def alembic_config():
    from alembic.config import Config

    config = Config()  # no alembic.ini: env.py would otherwise call fileConfig (kills loggers)
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    return config


def run_alembic(url: URL, action: str, revision: str) -> None:
    """`alembic <action> <revision>` against `url` (action: upgrade or downgrade)."""
    from alembic import command
    from app.config import settings

    assert_local_url(url)
    previous = settings.database_url
    # env.py reads settings.database_url; the validator does not run on assignment.
    settings.database_url = url.render_as_string(hide_password=False)
    try:
        assert_local_url(settings.database_url)  # right before Alembic touches anything
        getattr(command, action)(alembic_config(), revision)
    finally:
        settings.database_url = previous


@pytest.fixture(scope="session")
def pg_url(pg_admin_url) -> Iterator[URL]:
    """URL of a fresh throwaway database migrated to head."""
    with scratch_database(pg_admin_url) as url:
        run_alembic(url, "upgrade", "head")
        yield url


@pytest.fixture(scope="session")
def pg_engine(pg_url) -> Iterator[Engine]:
    engine = make_engine(pg_url)
    try:
        yield engine
    finally:
        engine.dispose()


def truncate_all(engine: Engine) -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        assert_test_database(conn)
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid()"
            )
        )
        tables = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
                "AND table_name <> 'alembic_version' ORDER BY table_name"
            )
        ).scalars().all()
        conn.execute(text("SET lock_timeout = '5s'"))
        if tables:
            names = ", ".join(f'"{t}"' for t in tables)
            conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


@pytest.fixture
def pg_clean(pg_engine) -> Iterator[Engine]:
    """Empty app tables before the test (alembic_version stays); yields the test engine."""
    truncate_all(pg_engine)
    yield pg_engine


@pytest.fixture
def pg_app(pg_url, pg_clean, auth_settings) -> Iterator[SimpleNamespace]:
    """Point the app (app.db) at the test database for one test; restore afterwards.

    Gives `.engine`, `.session()` (a new Session; the caller closes it) and `.client`
    (a TestClient on app.main.app, not entered as a context manager, so no lifespan).
    """
    from fastapi.testclient import TestClient

    from app import db
    from app.main import app

    engine = make_engine(pg_url)
    previous_engine = db._engine
    previous_bind = db.SessionLocal.kw.get("bind")
    db._engine = engine
    db.SessionLocal.configure(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield SimpleNamespace(
            engine=engine, session=factory, client=TestClient(app), settings=auth_settings
        )
    finally:
        db._engine = previous_engine
        db.SessionLocal.configure(bind=previous_bind)
        engine.dispose()


# --- helpers for tests --------------------------------------------------------------------------


def make_user_token(session: Session, email: str = "pg-user@example.com") -> tuple[Any, dict]:
    """Create and commit an active user; return (user, Authorization headers).

    Needs settings.jwt_secret (the `auth_settings` fixture, which `pg_app` already uses).
    """
    from app.models.user import User
    from app.services.auth import create_access_token, hash_password

    user = User(email=email, password_hash=hash_password("Sup3r-secret-pw!"), is_active=True)
    session.add(user)
    session.commit()
    token, _expires = create_access_token(user)
    return user, {"Authorization": f"Bearer {token}"}


@dataclass
class Outcome:
    value: Any = None
    error: BaseException | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def run_concurrently(*callables: Callable[[], Any], timeout: float = 20) -> list[Outcome]:
    """Run each callable in its own thread (it must open its own Session/connection).

    Returns one Outcome per callable, in order. Fails the test if any is still running after
    `timeout` seconds (a deadlock or hang), instead of hanging the run.
    """
    outcomes = [Outcome() for _ in callables]

    def worker(index: int, func: Callable[[], Any]) -> None:
        try:
            outcomes[index].value = func()
        except BaseException as exc:  # noqa: BLE001 - reported to the test, not swallowed
            outcomes[index].error = exc

    threads = [
        threading.Thread(target=worker, args=(i, func), daemon=True, name=f"pg-worker-{i}")
        for i, func in enumerate(callables)
    ]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + timeout
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    stuck = [t.name for t in threads if t.is_alive()]
    if stuck:
        pytest.fail(f"run_concurrently: still running after {timeout}s (hang or deadlock): {stuck}")
    return outcomes


def wait_for_lock_wait(engine: Engine, timeout: float = 10, min_waiting: int = 1) -> int:
    """Poll until at least `min_waiting` other backends of this database wait on a lock.

    Returns how many are waiting. Fails the test on timeout (proves the lock never contended).
    """
    deadline = time.monotonic() + timeout
    sql = text(
        "SELECT count(*) FROM pg_stat_activity a WHERE a.datname = current_database() "
        "AND a.pid <> pg_backend_pid() AND a.wait_event_type = 'Lock' "
        "AND EXISTS (SELECT 1 FROM pg_locks l WHERE l.pid = a.pid AND NOT l.granted)"
    )
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        while True:
            waiting = conn.execute(sql).scalar_one()
            if waiting >= min_waiting:
                return int(waiting)
            if time.monotonic() >= deadline:
                pytest.fail(f"no backend was waiting on a lock after {timeout}s")
            time.sleep(0.02)

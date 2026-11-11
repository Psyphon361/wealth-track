"""Tests of the pg harness itself: safety guards, migrations on real Postgres, constraints."""

import importlib.util
import socket
import time

import pytest
from sqlalchemy import CheckConstraint, text
from sqlalchemy.engine import make_url

from tests.pg.conftest import (
    API_DIR,
    TEST_DB_PREFIX,
    _SocketGuard,
    assert_local_url,
    assert_test_database,
    make_engine,
    normalise_url,
    require_pg_missing_url,
    run_alembic,
    run_concurrently,
    scratch_database,
    wait_for_lock_wait,
)

pg = pytest.mark.pg


# --- pure functions (no database) ---------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:p@ep-foo-123.us-east-2.aws.neon.tech/neondb?sslmode=require",
        "postgresql://u:p@ep-foo-pooler.neon.tech/db",
        "postgresql://u:p@db.example.com:5432/db",
        "postgresql://u:p@10.0.0.5/db",
        "postgresql://u:p@localhost.evil.com/db",
        "postgresql://u:p@/db",
        "postgresql://u:p@localhost/db?hostaddr=203.0.113.9",
        "postgresql://u:p@localhost/db?host=ep-foo.neon.tech",
        "mysql://u:p@localhost/db",
    ],
)
def test_allowlist_refuses_remote_hosts(url):
    with pytest.raises(RuntimeError):
        assert_local_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://postgres@localhost:5544/postgres",
        "postgresql://postgres@127.0.0.1:5544/postgres",
        "postgresql://postgres@[::1]:5544/postgres",
        "postgresql://postgres@/postgres?host=/tmp/pgsock",
        "postgresql+psycopg://postgres@127.0.0.1/postgres",
    ],
)
def test_allowlist_accepts_local_hosts(url):
    assert assert_local_url(url) is not None


def test_normalise_url_uses_the_psycopg_driver():
    assert normalise_url("postgresql://u@127.0.0.1/db").drivername == "postgresql+psycopg"


def test_require_pg_logic():
    assert require_pg_missing_url({"REQUIRE_PG": "1"}) is True
    assert require_pg_missing_url({"REQUIRE_PG": "1", "TEST_DATABASE_URL": ""}) is True
    assert require_pg_missing_url({"REQUIRE_PG": "1", "TEST_DATABASE_URL": "x"}) is False
    assert require_pg_missing_url({"TEST_DATABASE_URL": ""}) is False
    assert require_pg_missing_url({}) is False


def test_make_engine_refuses_remote_url():
    with pytest.raises(RuntimeError):
        make_engine(make_url("postgresql+psycopg://u:p@ep-foo.neon.tech/db"))


def test_socket_guard_blocks_non_local_and_restores():
    original_connect = socket.socket.connect
    guard = _SocketGuard()
    guard.install()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        with sock, pytest.raises(RuntimeError, match="socket guard"):
            sock.connect(("203.0.113.9", 80))
        with pytest.raises(RuntimeError, match="socket guard"):
            socket.create_connection(("mfapi.in", 443), timeout=1)
        with pytest.raises(RuntimeError, match="socket guard"):
            socket.getaddrinfo("api.mfapi.in", 443)
        assert socket.getaddrinfo("localhost", 80)  # local lookups still work
    finally:
        guard.remove()
    assert socket.socket.connect is original_connect


def test_run_concurrently_collects_results_and_errors():
    def fails():
        raise ValueError("boom")

    outcomes = run_concurrently(lambda: 7, fails)
    assert outcomes[0].ok and outcomes[0].value == 7
    assert isinstance(outcomes[1].error, ValueError)


def test_run_concurrently_fails_on_timeout():
    with pytest.raises(pytest.fail.Exception, match="hang or deadlock"):
        run_concurrently(lambda: time.sleep(3), timeout=0.5)


# --- real Postgres ------------------------------------------------------------------------------


def _load_0032():
    path = API_DIR / "alembic" / "versions" / "0032_db_constraints.py"
    spec = importlib.util.spec_from_file_location("migration_0032", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _script_head() -> str:
    from alembic.script import ScriptDirectory

    from tests.pg.conftest import alembic_config

    return ScriptDirectory.from_config(alembic_config()).get_current_head()


@pg
def test_connected_to_a_throwaway_database(pg_engine):
    with pg_engine.connect() as conn:
        assert conn.execute(text("SELECT current_database()")).scalar_one().startswith(
            TEST_DB_PREFIX
        )
        assert_test_database(conn)


@pg
def test_non_test_database_is_refused(pg_admin_url):
    admin = make_engine(pg_admin_url, test_database=False)
    try:
        with admin.connect() as conn, pytest.raises(RuntimeError, match="not a wt_test_"):
            assert_test_database(conn)
    finally:
        admin.dispose()


@pg
def test_upgrade_head_from_empty_reaches_script_head(pg_engine):
    with pg_engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == _script_head()


@pg
def test_pg_trgm_extension_exists(pg_engine):
    with pg_engine.connect() as conn:
        found = conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")).first()
    assert found is not None


@pg
def test_downgrade_then_upgrade_round_trip(pg_admin_url):
    with scratch_database(pg_admin_url) as url:
        run_alembic(url, "upgrade", "head")
        run_alembic(url, "downgrade", "0031")  # past 0032, which adds the ck_ constraints
        engine = make_engine(url)
        try:
            with engine.connect() as conn:
                version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                assert version != _script_head()
                gone = conn.execute(
                    text("SELECT count(*) FROM pg_constraint WHERE conname LIKE 'ck\\_%'")
                ).scalar_one()
            run_alembic(url, "upgrade", "head")
            with engine.connect() as conn:
                version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                back = conn.execute(
                    text("SELECT count(*) FROM pg_constraint WHERE conname LIKE 'ck\\_%'")
                ).scalar_one()
        finally:
            engine.dispose()
        assert version == _script_head()
        assert back > gone


@pg
def test_0032_constraints_and_funding_index_exist(pg_engine):
    migration = _load_0032()
    with pg_engine.connect() as conn:
        found = set(
            conn.execute(text("SELECT conname FROM pg_constraint WHERE contype = 'c'")).scalars()
        )
        index = conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE tablename = 'holding_fundings' AND indexname = 'uq_holding_fundings_active'"
            )
        ).scalar_one()
    names = {name for _table, name, _expr in migration.CHECKS}
    assert len(names) == len(migration.CHECKS)
    assert names <= found, sorted(names - found)
    assert "UNIQUE" in index
    assert "refunded_at IS NULL" in index


@pg
def test_model_check_constraint_names_match_postgres(pg_engine):
    import app.models  # noqa: F401  (registers every table)
    from app.db import Base

    declared: set[str] = set()
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            # Enum checks (stock_exchange, ...) have plain names; 0032 names start with ck_.
            if (
                isinstance(constraint, CheckConstraint)
                and constraint.name
                and constraint.name.startswith("ck_")
            ):
                declared.add(constraint.name)
    migration_names = {name for _table, name, _expr in _load_0032().CHECKS}
    # Every 0032 check is declared on a model (older ck_ checks, e.g. mf_sips day_of_month, too).
    assert migration_names <= declared, sorted(migration_names - declared)
    with pg_engine.connect() as conn:
        in_pg = set(
            conn.execute(
                text("SELECT conname FROM pg_constraint WHERE contype = 'c' AND conname LIKE 'ck\\_%'")
            ).scalars()
        )
    assert in_pg == declared


@pg
def test_pg_clean_empties_tables_but_keeps_alembic_version(pg_clean):
    with pg_clean.begin() as conn:
        conn.execute(text("INSERT INTO users (email) VALUES ('clean-probe@example.com')"))
    from tests.pg.conftest import truncate_all

    truncate_all(pg_clean)
    with pg_clean.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM users")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM alembic_version")).scalar_one() == 1


@pg
def test_pg_app_redirects_the_app_engine_and_restores(pg_app):
    from app import db

    assert db.get_engine() is pg_app.engine
    assert db.SessionLocal.kw["bind"] is pg_app.engine
    with pg_app.session() as session:
        user, headers = __import__("tests.pg.conftest", fromlist=["x"]).make_user_token(session)
    response = pg_app.client.get("/api/auth/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["email"] == user.email


@pg
def test_wait_for_lock_wait_sees_a_blocked_backend(pg_clean):
    holder = pg_clean.connect()
    try:
        holder.execute(text("LOCK TABLE users IN ACCESS EXCLUSIVE MODE"))

        def blocked():
            with pg_clean.connect() as conn:
                return conn.execute(text("SELECT count(*) FROM users")).scalar_one()

        import threading

        results = []
        thread = threading.Thread(target=lambda: results.append(blocked()), daemon=True)
        thread.start()
        assert wait_for_lock_wait(pg_clean) >= 1
        holder.commit()
        thread.join(10)
        assert results == [0]
    finally:
        holder.close()

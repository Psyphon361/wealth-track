"""The nightly invariant check (scripts/check_invariants.py, scripts/invariants.sql) on real Postgres.

A world built through the real API must have zero violations. Then each invariant gets one
deliberate violation written with raw SQL inside a transaction that is rolled back, and must be
reported by name. The runner itself must refuse to write.
"""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.pg.helpers_t3 import FD, FUND, World, stock_body

pytestmark = pytest.mark.pg

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_invariants.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("check_invariants", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def runner():
    return load_runner()


@pytest.fixture
def world(pg_app):
    w = World(pg_app)
    cash = w.add_cash("HDFC Savings", 500000)
    # a stock bought with cash, then sold in full into the same account
    sold = w.add_paid("stock", stock_body("Sold Ltd"), cash).json()["id"]
    assert w.sell_stock(sold, 100, 80, to_cash=cash).status_code in (200, 201)
    # a stock bought with cash and bought-and-deleted (funding refunded), one restored
    gone = w.add_paid("stock", stock_body("Gone Ltd"), cash).json()["id"]
    assert w.delete("stock", gone).status_code == 200
    back = w.add_paid("stock", stock_body("Back Ltd"), cash).json()["id"]
    assert w.delete("stock", back).status_code == 200
    assert w.restore("stock", back).status_code == 200
    # a stock sold in part
    part = w.add("stock", stock_body("Part Ltd", 100))
    assert w.sell_stock(part, 40, 90).status_code in (200, 201)
    # funds: one sold in part (opening purchase + redemption), one untouched, one sold fully
    w.seed_funds()
    fund = w.add("mf", FUND)
    assert w.sell("mf", fund, quantity=10, price=45).status_code in (200, 201)
    fund2 = w.add("mf", {**FUND, "scheme_name": "Fund B"})
    assert w.sell("mf", fund2, quantity=100, price=45).status_code in (200, 201)
    # a matured deposit settled into cash
    fd = w.add("fd", FD)
    assert w.settle("fd", fd, {"kind": "cash_existing", "cash_id": cash}).status_code in (200, 201)
    plain = w.add("stock", stock_body("Plain Ltd"))
    w.ids = {"plain": plain, "cash": cash, "sold": sold, "gone": gone, "back": back, "part": part, "fund": fund, "fd": fd}
    return w


def check(runner, world, violate=None):
    """Run every check in a transaction that is rolled back; `violate` writes first."""
    with world.engine.connect() as conn:
        if violate is None:
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
        else:
            violate(conn)
        try:
            return runner.run_checks(conn)
        finally:
            conn.rollback()


def test_clean_world_has_no_violations(runner, world):
    assert world.count("holding_exits") >= 5 and world.count("holding_fundings") >= 3
    results = check(runner, world)
    assert set(results) == {name for name, _ in runner.load_queries()}
    assert {name: rows for name, rows in results.items() if rows} == {}


def test_runner_main_exit_codes(runner, world, pg_url, monkeypatch, capsys):
    url = pg_url.render_as_string(hide_password=False)
    assert runner.main(["x", url]) == 0
    out = capsys.readouterr().out
    assert "0 violation(s)" in out and url not in out
    assert runner.main(["x", "postgresql://nobody@127.0.0.1:1/none"]) == 2
    assert "127.0.0.1" not in capsys.readouterr().out
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert runner.main(["x"]) == 2


def test_runner_connection_refuses_writes(runner, world, pg_url):
    conn = runner.open_readonly(pg_url.render_as_string(hide_password=False))
    try:
        with pytest.raises(DBAPIError):
            conn.exec_driver_sql("UPDATE cash_holdings SET balance = balance")
    finally:
        conn.rollback()
        conn.close()


def fk_name(conn, table: str, target: str) -> str:
    return conn.execute(
        text(
            "SELECT conname FROM pg_constraint WHERE contype = 'f' "
            "AND conrelid = CAST(:t AS regclass) AND confrelid = CAST(:r AS regclass)"
        ),
        {"t": table, "r": target},
    ).scalar_one()


def sql(statement: str):
    return lambda conn: conn.execute(text(statement))


def violations(ids):
    sold, back, part, fund, cash = ids["sold"], ids["back"], ids["part"], ids["fund"], ids["cash"]

    def orphan_funding(conn):
        conn.execute(text(f"DELETE FROM stocks WHERE id = {back}"))  # noqa: S608

    def orphan_exit(conn):
        conn.execute(text(f"DELETE FROM stocks WHERE id = {part}"))  # noqa: S608

    def duplicate_funding(conn):
        conn.execute(text("DROP INDEX uq_holding_fundings_active"))
        conn.execute(
            text(
                "INSERT INTO holding_fundings (user_id, asset_type, holding_id, cash_holding_id, amount, "
                "funded_on, prev_balance_date) SELECT user_id, asset_type, holding_id, cash_holding_id, "
                "amount, funded_on, prev_balance_date FROM holding_fundings WHERE refunded_at IS NULL"
            )
        )

    def duplicate_settlement(conn):
        conn.execute(text("DROP INDEX uq_holding_exits_maturity"))
        conn.execute(
            text(
                "INSERT INTO holding_exits (user_id, asset_type, holding_id, kind, exit_date, amount, cost, "
                "destination) SELECT user_id, asset_type, holding_id, kind, exit_date, amount, cost, "
                "destination FROM holding_exits WHERE kind = 'maturity'"
            )
        )

    def negative_cash(conn):
        conn.execute(text("ALTER TABLE cash_holdings DROP CONSTRAINT ck_cash_holdings_balance_nonnegative"))
        conn.execute(text(f"UPDATE cash_holdings SET balance = -1 WHERE id = {cash}"))  # noqa: S608

    def missing_fund(conn):
        name = fk_name(conn, "mf_transactions", "mutual_funds")
        conn.execute(text(f"ALTER TABLE mf_transactions DROP CONSTRAINT {name}"))  # noqa: S608
        conn.execute(text("DELETE FROM mutual_funds WHERE id = {}".format(fund)))  # noqa: S608

    return {
        "orphan_exit": orphan_exit,
        "orphan_funding": orphan_funding,
        "funding_state_mismatch": sql(
            f"UPDATE holding_fundings SET refunded_at = now() WHERE asset_type = 'stock' AND holding_id = {back}"  # noqa: S608
        ),
        "negative_cash": negative_cash,
        "duplicate_active_funding": duplicate_funding,
        "duplicate_settlement": duplicate_settlement,
        "mf_units_vs_transactions": sql(f"UPDATE mutual_funds SET units = units + 1 WHERE id = {fund}"),  # noqa: S608
        "mf_transaction_missing_fund": missing_fund,
        "closed_without_sale": sql(f"UPDATE stocks SET closed_on = '2026-02-01' WHERE id = {ids['plain']}"),  # noqa: S608
        "sale_cost_vs_invested": sql(
            f"UPDATE holding_exits SET cost = cost + 5 WHERE asset_type = 'stock' AND holding_id = {sold}"  # noqa: S608
        ),
        "invalid_constraint": sql(
            "ALTER TABLE cash_holdings ADD CONSTRAINT zz_probe CHECK (balance > 1000000000) NOT VALID"
        ),
        "missing_funding_unique_index": sql("DROP INDEX uq_holding_fundings_active"),
    }


def test_every_invariant_is_detected(runner, world):
    cases = violations(world.ids)
    assert set(cases) == {name for name, _ in runner.load_queries()}, "a check has no violation test"
    for name, violate in cases.items():
        results = check(runner, world, violate)
        assert results[name], f"{name} was not detected"
    # nothing leaked: the world is clean again after the rollbacks
    assert {n: r for n, r in check(runner, world).items() if r} == {}

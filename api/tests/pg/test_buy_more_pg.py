"""Buy more (and undoing a buy) racing other writers of one fund, on real Postgres (marker pg).

Same method as test_concurrency_pg.py: the first call is held INSIDE the fund's row lock, the second
is seen waiting on it, then the first is released (helpers_t3.staged). Each test checks the exact
status the loser gets and the committed data (units, invested, transactions) plus the invariants.
Also the migration 0033 round trip (upgrade, downgrade to 0032, upgrade) on a scratch database.

Fund: 100 units, Rs 4,000, bought 2025-06-01 (opening transaction made by the first buy). A buy of
Rs 1,000 at NAV 50 is 20 units. SIP: Rs 5,000 on the 5th from 2026-01-05, posted for 2026-03-10
(3 instalments of 99.995 units at NAV 50 less stamp duty).
"""

from decimal import Decimal

import pytest
from sqlalchemy import text

from app.schemas.buys import (
    BUY_DATE_BEFORE_LAST_SALE_ERROR,
    BUY_DUPLICATE_MESSAGE,
    BUY_UNDO_SALE_FIRST_MESSAGE,
)
from app.services import buys as buys_service
from app.services import cas_import
from app.services import exits as exits_service
from app.services import sip as sip_service
from tests.pg.conftest import make_engine, run_alembic, scratch_database
from tests.pg.helpers_t3 import FUND, World, assert_clean, check_invariants, hold_after, staged, statuses

pytestmark = pytest.mark.pg

BUY_DAY = "2026-01-15"
SIP_UNITS = 3 * Decimal("99.995")


@pytest.fixture
def w(pg_app):
    world = World(pg_app)
    world.seed_funds()  # MF master 100 (CAS commit, SIP) and its NAV history
    return world


def buy(world, fund, date=BUY_DAY, amount=1000, nav=50, **query):
    return world.call(
        "POST", f"/api/holdings/mf/{fund}/buy", json={"date": date, "amount": amount, "nav": nav},
        params=query or None,
    )  # fmt: skip


def undo_buy(world, fund, txn_id):
    return world.call("DELETE", f"/api/holdings/mf/{fund}/buys/{txn_id}")


def message(response) -> str:
    body = response.json()
    detail = body.get("detail")
    if isinstance(detail, list):
        return detail[0]["msg"]
    return detail["message"] if isinstance(detail, dict) else body.get("message", "")


def fund_with_buy(world, date=BUY_DAY):
    fund = world.add("mf", FUND)
    r = buy(world, fund, date)
    assert r.status_code == 201, r.text
    return fund, r.json()["transaction_id"]


def manual_rows(world, fund):
    return world.rows(
        "SELECT id FROM mf_transactions WHERE mutual_fund_id = :f AND manual ORDER BY id", f=fund
    )


# --- buy vs sell ----------------------------------------------------------------------------------


def test_sale_waits_for_a_buy_and_sells_the_bought_units(w, monkeypatch):
    fund = w.add("mf", FUND)
    gate = hold_after(monkeypatch, buys_service, "record_mf_buy")
    a, b = staged(
        w.engine, gate, lambda: buy(w, fund),
        lambda: w.sell("mf", fund, quantity=110, price=60, date=BUY_DAY),
    )  # fmt: skip
    bought, sold = assert_clean(a, b)
    assert statuses(bought, sold) == [201, 201], (bought.text, sold.text)  # 110 > the 100 held before the buy
    row = w.holding("mutual_funds", fund)
    assert row.units == Decimal("10") and row.closed_on is None
    assert len(w.exits("mf", fund)) == 1 and len(manual_rows(w, fund)) == 1
    check_invariants(w)


def test_buy_waits_for_a_sale_and_is_refused_a_date_before_it(w, monkeypatch):
    fund = w.add("mf", FUND)
    gate = hold_after(monkeypatch, exits_service, "record_sale")
    a, b = staged(
        w.engine, gate, lambda: w.sell("mf", fund, quantity=10, price=60, date=BUY_DAY),
        lambda: buy(w, fund, "2026-01-14"),
    )  # fmt: skip
    sold, bought = assert_clean(a, b)
    assert sold.status_code == 201, sold.text
    assert bought.status_code == 422 and message(bought) == BUY_DATE_BEFORE_LAST_SALE_ERROR
    row = w.holding("mutual_funds", fund)
    assert row.units == Decimal("90") and manual_rows(w, fund) == []
    check_invariants(w)


def test_buy_waits_for_a_sale_and_lands_on_the_sale_date(w, monkeypatch):
    fund = w.add("mf", FUND)
    gate = hold_after(monkeypatch, exits_service, "record_sale")
    a, b = staged(
        w.engine, gate, lambda: w.sell("mf", fund, quantity=10, price=60, date=BUY_DAY),
        lambda: buy(w, fund, BUY_DAY),
    )  # fmt: skip
    assert statuses(*assert_clean(a, b)) == [201, 201]
    assert w.holding("mutual_funds", fund).units == Decimal("110")  # 100 - 10 + 20
    check_invariants(w)


def test_buy_waits_for_a_full_sale_and_gets_409(w, monkeypatch):
    fund = w.add("mf", FUND)
    gate = hold_after(monkeypatch, exits_service, "record_sale")
    a, b = staged(
        w.engine, gate, lambda: w.sell("mf", fund, quantity=100, price=60, date=BUY_DAY),
        lambda: buy(w, fund),
    )  # fmt: skip
    sold, bought = assert_clean(a, b)
    assert statuses(sold, bought) == [201, 409], (sold.text, bought.text)
    row = w.holding("mutual_funds", fund)
    assert row.closed_on is not None and row.units == Decimal("100") and manual_rows(w, fund) == []
    check_invariants(w)


# --- buy vs buy -----------------------------------------------------------------------------------


def test_the_same_buy_twice_at_once_loser_gets_the_duplicate_409(w, monkeypatch):
    fund = w.add("mf", FUND)
    gate = hold_after(monkeypatch, buys_service, "record_mf_buy")
    a, b = staged(w.engine, gate, lambda: buy(w, fund), lambda: buy(w, fund))
    first, second = assert_clean(a, b)
    assert statuses(first, second) == [201, 409], (first.text, second.text)
    assert message(second) == BUY_DUPLICATE_MESSAGE
    assert len(manual_rows(w, fund)) == 1
    row = w.holding("mutual_funds", fund)
    assert (row.units, row.invested_amount) == (Decimal("120"), Decimal("5000"))
    check_invariants(w)


def test_two_different_buys_at_once_both_land_in_turn(w, monkeypatch):
    fund = w.add("mf", FUND)
    gate = hold_after(monkeypatch, buys_service, "record_mf_buy")
    a, b = staged(
        w.engine, gate, lambda: buy(w, fund, amount=1000), lambda: buy(w, fund, amount=500),
    )  # fmt: skip
    assert statuses(*assert_clean(a, b)) == [201, 201]
    assert len(manual_rows(w, fund)) == 2
    row = w.holding("mutual_funds", fund)
    assert (row.units, row.invested_amount) == (Decimal("130"), Decimal("5500"))  # 100 + 20 + 10
    assert w.scalar("SELECT count(*) FROM mf_transactions WHERE mutual_fund_id = :f AND NOT manual", f=fund) == 1
    check_invariants(w)


# --- buy vs SIP posting ---------------------------------------------------------------------------


def test_post_due_waits_for_a_buy_and_both_land(w, monkeypatch):
    fund = w.add("mf", FUND)
    sip = w.add_sip(fund)
    gate = hold_after(monkeypatch, buys_service, "record_mf_buy")
    a, b = staged(w.engine, gate, lambda: buy(w, fund), w.post_due)
    bought, posted = assert_clean(a, b)
    assert bought.status_code == 201, bought.text
    assert posted == {sip: 3}
    row = w.holding("mutual_funds", fund)
    assert row.units == Decimal("100") + 20 + SIP_UNITS
    assert row.invested_amount == Decimal("4000") + 1000 + 3 * Decimal("5000")
    check_invariants(w)


def test_buy_waits_for_post_due_and_both_land(w, monkeypatch):
    fund = w.add("mf", FUND)
    sip = w.add_sip(fund)
    gate = hold_after(monkeypatch, sip_service, "nav_for_due", lambda a, k: k.get("fetch") is False)
    a, b = staged(w.engine, gate, w.post_due, lambda: buy(w, fund))
    posted, bought = assert_clean(a, b)
    assert posted == {sip: 3}
    assert bought.status_code == 201, bought.text
    row = w.holding("mutual_funds", fund)
    assert row.units == Decimal("100") + 20 + SIP_UNITS
    assert row.invested_amount == Decimal("4000") + 1000 + 3 * Decimal("5000")
    assert len(manual_rows(w, fund)) == 1
    check_invariants(w)


# --- undo vs sell ---------------------------------------------------------------------------------


def test_sale_waits_for_an_undo_and_sells_what_is_left(w, monkeypatch):
    fund, txn = fund_with_buy(w)
    gate = hold_after(monkeypatch, buys_service, "undo_mf_buy")
    a, b = staged(
        w.engine, gate, lambda: undo_buy(w, fund, txn),
        lambda: w.sell("mf", fund, quantity=10, price=60, date="2026-03-01"),
    )  # fmt: skip
    undone, sold = assert_clean(a, b)
    assert statuses(undone, sold) == [200, 201], (undone.text, sold.text)
    assert manual_rows(w, fund) == []
    assert w.holding("mutual_funds", fund).units == Decimal("90")
    check_invariants(w)


def test_undo_waits_for_a_sale_and_is_refused_until_it_is_undone(w, monkeypatch):
    fund, txn = fund_with_buy(w)
    gate = hold_after(monkeypatch, exits_service, "record_sale")
    a, b = staged(
        w.engine, gate, lambda: w.sell("mf", fund, quantity=10, price=60, date="2026-03-01"),
        lambda: undo_buy(w, fund, txn),
    )  # fmt: skip
    sold, undone = assert_clean(a, b)
    assert sold.status_code == 201, sold.text
    assert undone.status_code == 409 and message(undone) == BUY_UNDO_SALE_FIRST_MESSAGE
    assert len(manual_rows(w, fund)) == 1
    assert w.holding("mutual_funds", fund).units == Decimal("110")
    check_invariants(w)


# --- undo vs SIP posting --------------------------------------------------------------------------


def test_post_due_waits_for_an_undo_and_both_land(w, monkeypatch):
    fund, txn = fund_with_buy(w, "2026-01-02")
    sip = w.add_sip(fund)
    gate = hold_after(monkeypatch, buys_service, "undo_mf_buy")
    a, b = staged(w.engine, gate, lambda: undo_buy(w, fund, txn), w.post_due)
    undone, posted = assert_clean(a, b)
    assert undone.status_code == 200, undone.text
    assert posted == {sip: 3}
    row = w.holding("mutual_funds", fund)
    assert row.units == Decimal("100") + SIP_UNITS
    assert row.invested_amount == Decimal("4000") + 3 * Decimal("5000")
    assert manual_rows(w, fund) == []
    check_invariants(w)


def test_undo_waits_for_post_due_and_both_land(w, monkeypatch):
    fund, txn = fund_with_buy(w, "2026-01-02")
    sip = w.add_sip(fund)
    gate = hold_after(monkeypatch, sip_service, "nav_for_due", lambda a, k: k.get("fetch") is False)
    a, b = staged(w.engine, gate, w.post_due, lambda: undo_buy(w, fund, txn))
    posted, undone = assert_clean(a, b)
    assert posted == {sip: 3}
    assert undone.status_code == 200, undone.text
    row = w.holding("mutual_funds", fund)
    assert row.units == Decimal("100") + SIP_UNITS
    assert row.invested_amount == Decimal("4000") + 3 * Decimal("5000")
    assert manual_rows(w, fund) == []
    check_invariants(w)


# --- undo vs CAS commit ---------------------------------------------------------------------------


def cas_update(world, fund):
    row = dict(
        action="update", holding_id=fund, scheme_code=100, scheme_name="x", category="equity",
        units=50, avg_nav=20, invested_amount=1000, purchase_date="2025-06-01",
    )  # fmt: skip
    return world.call("POST", "/api/import/cas/commit", json={"rows": [row]})


def test_cas_commit_waits_for_an_undo_and_replaces_the_totals(w, monkeypatch):
    fund, txn = fund_with_buy(w)
    gate = hold_after(monkeypatch, buys_service, "undo_mf_buy")
    a, b = staged(w.engine, gate, lambda: undo_buy(w, fund, txn), lambda: cas_update(w, fund))
    undone, imported = assert_clean(a, b)
    assert statuses(undone, imported) == [200, 200], (undone.text, imported.text)
    row = w.holding("mutual_funds", fund)
    assert (row.units, row.invested_amount) == (Decimal("50"), Decimal("1000"))
    assert w.count("mf_transactions") == 0
    check_invariants(w)


def test_undo_waits_for_a_cas_commit_and_finds_the_record_gone(w, monkeypatch):
    fund, txn = fund_with_buy(w)
    gate = hold_after(monkeypatch, cas_import, "save_transactions")
    a, b = staged(w.engine, gate, lambda: cas_update(w, fund), lambda: undo_buy(w, fund, txn))
    imported, undone = assert_clean(a, b)
    assert imported.status_code == 200, imported.text
    assert undone.status_code == 404 and message(undone) == "Record not found"
    row = w.holding("mutual_funds", fund)
    assert (row.units, row.invested_amount) == (Decimal("50"), Decimal("1000"))
    assert w.count("mf_transactions") == 0
    check_invariants(w)


# --- migration 0033 -------------------------------------------------------------------------------


def manual_column(engine):
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT is_nullable, column_default, data_type FROM information_schema.columns "
                "WHERE table_name = 'mf_transactions' AND column_name = 'manual'"
            )
        ).first()


def test_migration_0033_round_trip_adds_manual_default_false(pg_admin_url):
    with scratch_database(pg_admin_url) as url:
        run_alembic(url, "upgrade", "head")
        engine = make_engine(url)
        try:
            column = manual_column(engine)
            assert column is not None
            assert (column.is_nullable, column.column_default, column.data_type) == ("NO", "false", "boolean")
            run_alembic(url, "downgrade", "0032")
            assert manual_column(engine) is None
            run_alembic(url, "upgrade", "head")
            column = manual_column(engine)
            assert column is not None
            assert (column.is_nullable, column.column_default, column.data_type) == ("NO", "false", "boolean")
        finally:
            engine.dispose()

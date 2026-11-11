"""Buy more for mutual funds: POST /api/holdings/mf/{id}/buy and DELETE .../buys/{txn_id} (SQLite)."""

from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import HoldingExit, MFTransaction, MutualFund
from app.schemas.buys import BuyBody
from app.services import buys as buys_service
from app.services.exits import ExitConflict, ExitError
from tests.test_exits_api import FUND, SELL_DAY, add, asset, fund_item, sell
from tests.test_exits_api import errors as _errors
from tests.test_scoping import client, users  # noqa: F401  (fixtures)
from tests.test_sip_api import sc, start  # noqa: F401  (fixture: today is 2026-03-10, scheme 100)

D = Decimal
BUY_DAY = "2026-01-10"  # after the fund's purchase date (2025-06-01), before SELL_DAY
NAME = "Fund A - Direct Growth"  # the stored name comes from the MF master


def errors(response):
    loc, message = _errors(response)
    return tuple(loc), message


def buy(sc, headers, fund_id, confirm=False, **overrides):  # noqa: F811
    body = {"date": BUY_DAY, "amount": 1000, "nav": 50, **overrides}
    body = {k: v for k, v in body.items() if v is not None}
    url = f"/api/holdings/mf/{fund_id}/buy" + ("?confirm_duplicate=true" if confirm else "")
    return sc.post(url, json=body, headers=headers)


def undo(sc, headers, fund_id, txn_id):  # noqa: F811
    return sc.delete(f"/api/holdings/mf/{fund_id}/buys/{txn_id}", headers=headers)


def transactions(sc, headers, fund_id):  # noqa: F811
    r = sc.get(f"/api/holdings/mf/{fund_id}/transactions", headers=headers)
    assert r.status_code == 200
    return r.json()["items"]


def new_fund(sc, headers):  # noqa: F811
    return add(sc, headers, "mf", FUND)  # 100 units, average NAV 40, invested 4,000, bought 2025-06-01


def patch_fund(engine, fund_id, **fields):
    with sessionmaker(bind=engine)() as s:
        fund = s.get(MutualFund, fund_id)
        for key, value in fields.items():
            setattr(fund, key, value)
        s.commit()


def add_txn(engine, fund_id, day, kind="purchase", amount=100, units=1, **extra):
    with sessionmaker(bind=engine)() as s:
        row = MFTransaction(
            mutual_fund_id=fund_id, txn_date=day, kind=kind, amount=D(amount), units=D(units), **extra
        )
        s.add(row)
        s.commit()
        return row.id


# --- validation ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides, loc, message",
    [
        ({"date": "2026-03-11"}, ("date",), "Date can't be in the future"),
        ({"date": "1989-12-31"}, ("date",), "Date must be on or after 1 Jan 1990"),
        ({"date": "2025-05-31"}, ("date",), "Date can't be before the purchase date"),
        ({"amount": 0}, ("amount",), "Must be greater than 0"),
        ({"amount": -5}, ("amount",), "Must be greater than 0"),
        ({"amount": 10.123}, ("amount",), "Up to 2 decimal places allowed"),
        ({"amount": 1000000001}, ("amount",), "Must be at most ₹100 crore"),
        ({"nav": 0}, ("nav",), "Must be greater than 0"),
        ({"nav": 12.34567}, ("nav",), "Up to 4 decimal places allowed"),
        ({"nav": 1000000001}, ("nav",), "Must be at most ₹100 crore"),
        ({"units": 0}, ("units",), "Must be greater than 0"),
        ({"units": 1.2345}, ("units",), "Up to 3 decimal places allowed"),
        ({"units": 10000001}, ("units",), "Must be at most 1 crore"),
        ({"amount": 0.01, "nav": 100}, ("units",), "Must be greater than 0"),  # 0.0001 units
    ],
)
def test_validation_messages(sc, users, overrides, loc, message):  # noqa: F811
    a = users[0]
    fund_id = new_fund(sc, a)
    r = buy(sc, a, fund_id, **overrides)
    assert r.status_code == 422, r.json()
    assert errors(r) == (loc, message)
    assert asset(sc, a, "mf", fund_id)["units"] == 100  # nothing written
    assert transactions(sc, a, fund_id) == []


@pytest.mark.parametrize("field, message", [("date", "Required"), ("amount", "Required"), ("nav", "Required")])
def test_required_fields(sc, users, field, message):  # noqa: F811
    a = users[0]
    fund_id = new_fund(sc, a)
    body = {"date": BUY_DAY, "amount": 1000, "nav": 50}
    del body[field]
    r = sc.post(f"/api/holdings/mf/{fund_id}/buy", json=body, headers=a)
    assert r.status_code == 422
    assert errors(r) == ((field,), message)


# --- the buy ------------------------------------------------------------------------------------


def test_buy_adds_units_and_cost_and_an_opening_transaction(sc, users):  # noqa: F811
    a = users[0]
    fund_id = new_fund(sc, a)
    r = buy(sc, a, fund_id)
    assert r.status_code == 201, r.json()
    body = r.json()
    assert body["message"] == "More units added"
    assert body["description"] == f"{NAME} · 20 units for ₹1,000"
    assert (body["units_added"], body["units"], body["invested_amount"]) == (20, 120, 5000)
    assert body["avg_nav"] == 41.6667  # 5,000 / 120, 4 dp
    held = asset(sc, a, "mf", fund_id)
    assert (held["units"], held["invested_amount"], held["avg_nav"]) == (120, 5000, 41.6667)
    assert held["purchase_date"] == "2025-06-01"  # a buy never moves it

    rows = transactions(sc, a, fund_id)
    assert [(t["date"], t["kind"], t["units"], t["amount"]) for t in rows] == [
        (BUY_DAY, "purchase", 20, 1000),
        ("2025-06-01", "purchase", 100, 4000),  # the opening purchase of what the fund already was
    ]
    assert body["transaction_id"] == rows[0]["id"]
    assert (rows[0]["manual"], rows[0]["sip"], rows[0]["nav"]) == (True, False, 50)
    assert rows[1]["manual"] is False


def test_units_default_rounds_half_up_and_a_statement_value_overrides_it(sc, users):  # noqa: F811
    a = users[0]
    fund_id = new_fund(sc, a)
    r = buy(sc, a, fund_id, amount=1000, nav=30)  # 33.3333... -> 33.333
    assert r.json()["units_added"] == 33.333
    r = buy(sc, a, fund_id, amount=100, nav=3, date="2026-01-11")  # 33.3333 -> 33.333
    assert r.json()["units_added"] == 33.333
    r = buy(sc, a, fund_id, amount=1, nav=0.8, date="2026-01-12")  # 1.25 exactly
    assert r.json()["units_added"] == 1.25
    r = buy(sc, a, fund_id, amount=5000, nav=50, units=99.995, date="2026-01-13")  # after stamp duty
    assert r.json()["units_added"] == 99.995
    held = asset(sc, a, "mf", fund_id)
    assert held["units"] == pytest.approx(100 + 33.333 + 33.333 + 1.25 + 99.995)
    assert held["invested_amount"] == 4000 + 1000 + 100 + 1 + 5000


def test_a_buy_on_the_purchase_date_is_allowed(sc, users):  # noqa: F811
    a = users[0]
    fund_id = new_fund(sc, a)
    assert buy(sc, a, fund_id, date="2025-06-01").status_code == 201
    assert asset(sc, a, "mf", fund_id)["purchase_date"] == "2025-06-01"


def test_a_fund_with_transactions_that_do_not_match_still_buys(sc, users, auth_engine):  # noqa: F811
    a = users[0]
    fund_id = new_fund(sc, a)
    add_txn(auth_engine, fund_id, date(2025, 6, 1), amount=500, units=5)  # holding says 100 units
    r = buy(sc, a, fund_id)
    assert r.status_code == 201, r.json()
    assert asset(sc, a, "mf", fund_id)["units"] == 120
    assert len(transactions(sc, a, fund_id)) == 2  # no opening row added on top of the existing one


def test_xirr_stays_on_transactions_after_a_buy(sc, users):  # noqa: F811
    a = users[0]
    fund_id = new_fund(sc, a)
    assert fund_item(sc, a, fund_id)["xirr_basis"] != "transactions"
    assert buy(sc, a, fund_id).status_code == 201
    row = fund_item(sc, a, fund_id)
    assert row["xirr_basis"] == "transactions" and row["xirr_transactions"] == 2
    assert row["xirr"] is not None


def test_buy_then_partial_sale_uses_the_new_lot_and_undoing_the_sale_keeps_the_buy(sc, users):  # noqa: F811
    a = users[0]
    fund_id = new_fund(sc, a)  # 100 units for 4,000 on 2025-06-01
    bought = buy(sc, a, fund_id, amount=3000, nav=150).json()  # 20 units for 3,000
    sold = sell(sc, a, "mf", fund_id, quantity=110, price=50)
    assert sold.status_code == 201, sold.json()
    assert sold.json()["cost"] == 5500  # 100 old units (4,000) + half of the new lot (1,500)
    held = asset(sc, a, "mf", fund_id)
    assert (held["units"], held["invested_amount"]) == (10, 1500)

    assert undo(sc, a, fund_id, bought["transaction_id"]).status_code == 409  # the sale used them
    assert sc.delete(f"/api/exits/{sold.json()['id']}", headers=a).status_code == 200
    held = asset(sc, a, "mf", fund_id)
    assert (held["units"], held["invested_amount"]) == (120, 7000)
    assert undo(sc, a, fund_id, bought["transaction_id"]).status_code == 200
    held = asset(sc, a, "mf", fund_id)
    assert (held["units"], held["invested_amount"], held["avg_nav"]) == (100, 4000, 40)


# --- date against sales -------------------------------------------------------------------------


def test_a_date_before_the_last_sale_is_refused_and_the_same_day_is_allowed(sc, users):  # noqa: F811
    a = users[0]
    fund_id = new_fund(sc, a)
    assert sell(sc, a, "mf", fund_id, quantity=40, price=50).status_code == 201  # on SELL_DAY
    r = buy(sc, a, fund_id, date="2026-01-14")
    assert r.status_code == 422
    assert errors(r) == (("date",), "Date can't be before the last sale")
    r = buy(sc, a, fund_id, date=SELL_DAY)  # a partly sold fund can be bought into
    assert r.status_code == 201, r.json()
    held = asset(sc, a, "mf", fund_id)
    assert (held["units"], held["invested_amount"]) == (80, 3400)  # 60 left + 20 bought


def test_a_cas_redemption_row_also_counts_as_a_sale(sc, users, auth_engine):  # noqa: F811
    a = users[0]
    fund_id = new_fund(sc, a)
    add_txn(auth_engine, fund_id, date(2025, 6, 1), amount=4000, units=100)
    add_txn(auth_engine, fund_id, date(2026, 2, 1), kind="redemption", amount=100, units=1)
    r = buy(sc, a, fund_id, date="2026-01-31")
    assert r.status_code == 422
    assert errors(r) == (("date",), "Date can't be before the last sale")
    assert buy(sc, a, fund_id, date="2026-02-01").status_code == 201


def test_a_sale_exit_without_a_redemption_row_also_counts(sc, users, auth_engine):  # noqa: F811
    a = users[0]
    fund_id = new_fund(sc, a)
    with sessionmaker(bind=auth_engine)() as s:
        s.add(HoldingExit(
            user_id=s.get(MutualFund, fund_id).user_id, asset_type="mf", holding_id=fund_id,
            kind="sale", exit_date=date(2026, 2, 1), quantity=D(1), amount=D(100), cost=D(40),
            destination="none",
        ))  # fmt: skip
        s.commit()
    r = buy(sc, a, fund_id, date="2026-01-31")
    assert errors(r) == (("date",), "Date can't be before the last sale")
    assert buy(sc, a, fund_id, date="2026-02-01").status_code == 201


# --- refusals -----------------------------------------------------------------------------------


def test_a_closed_fund_is_refused(sc, users):  # noqa: F811
    a = users[0]
    fund_id = new_fund(sc, a)
    assert sell(sc, a, "mf", fund_id, quantity=100, price=50).status_code == 201
    r = buy(sc, a, fund_id, date="2026-02-01")
    assert r.status_code == 409
    assert r.json()["message"] == "Already sold"


def test_other_types_users_and_missing_ids_are_404(sc, users):  # noqa: F811
    a, _a_id, b, _b_id = users
    fund_id = new_fund(sc, a)
    stock_id = add(sc, a, "stock", {
        "name": "Acme Ltd", "exchange": "NSE", "quantity": 100, "avg_buy_price": 50,
        "buy_date": "2025-01-01",
    })  # fmt: skip
    sold_description = sell(sc, a, "gold", 1).json()["description"]  # "Can't be sold" 404 text
    r = sc.post(f"/api/holdings/stock/{stock_id}/buy", json={"date": BUY_DAY, "amount": 1, "nav": 1}, headers=a)
    assert r.status_code == 404
    assert r.json()["message"] == "Can't add to this holding"
    assert r.json()["description"] == sold_description
    for who, target in ((b, fund_id), (a, 99999)):
        r = buy(sc, who, target)
        assert r.status_code == 404
        assert r.json()["message"] == "Holding not found"
    assert sc.post(f"/api/holdings/mf/{fund_id}/buy", json={}).status_code == 401
    assert asset(sc, a, "mf", fund_id)["units"] == 100


# --- double submit ------------------------------------------------------------------------------


def test_the_same_buy_twice_is_a_duplicate_unless_confirmed(sc, users):  # noqa: F811
    a = users[0]
    fund_id = new_fund(sc, a)
    assert buy(sc, a, fund_id).status_code == 201
    r = buy(sc, a, fund_id)
    assert r.status_code == 409
    assert r.json()["message"] == "Looks like a buy you already made"
    assert r.json()["duplicates"] == [{"id": fund_id, "name": NAME}]
    assert "₹1,000" in r.json()["description"]
    assert asset(sc, a, "mf", fund_id)["units"] == 120

    assert buy(sc, a, fund_id, amount=1001).status_code == 201  # another amount is a new buy
    assert buy(sc, a, fund_id, confirm=True).status_code == 201
    assert asset(sc, a, "mf", fund_id)["units"] == 100 + 20 + 20.02 + 20


def test_a_sip_row_with_the_same_numbers_is_not_a_duplicate(sc, users, auth_engine):  # noqa: F811
    a = users[0]
    fund_id = new_fund(sc, a)
    add_txn(auth_engine, fund_id, date(2025, 6, 1), amount=4000, units=100)
    add_txn(auth_engine, fund_id, date(2026, 1, 10), amount=1000, units=20)  # imported, not manual
    assert buy(sc, a, fund_id).status_code == 201


# --- undo ---------------------------------------------------------------------------------------


def test_undo_restores_the_totals_and_leaves_the_purchase_date(sc, users):  # noqa: F811
    a = users[0]
    fund_id = new_fund(sc, a)
    txn_id = buy(sc, a, fund_id).json()["transaction_id"]
    row = transactions(sc, a, fund_id)[0]
    assert (row["manual"], row["undoable"]) == (True, True)
    r = undo(sc, a, fund_id, txn_id)
    assert r.status_code == 200, r.json()
    assert r.json() == {"message": "Buy undone", "description": f"{NAME} · 20 units removed."}
    held = asset(sc, a, "mf", fund_id)
    assert (held["units"], held["invested_amount"], held["avg_nav"]) == (100, 4000, 40)
    assert held["purchase_date"] == "2025-06-01"
    assert [t["id"] for t in transactions(sc, a, fund_id)] != [txn_id]
    again = undo(sc, a, fund_id, txn_id)  # second undo
    assert again.status_code == 404 and again.json()["message"] == "Record not found"


def test_undo_after_a_later_sip_instalment_keeps_the_instalments(sc, users):  # noqa: F811
    a = users[0]
    fund_id = new_fund(sc, a)
    txn_id = buy(sc, a, fund_id).json()["transaction_id"]
    sip = start(sc, a, start_date="2026-02-05")  # Groww, same fund: posts into this holding
    assert sip.status_code == 201 and sip.json()["instalments_added"] == 2
    assert sip.json()["mutual_fund_id"] == fund_id
    assert undo(sc, a, fund_id, txn_id).status_code == 200
    held = asset(sc, a, "mf", fund_id)
    assert held["units"] == pytest.approx(100 + 2 * 99.995)
    assert held["invested_amount"] == 4000 + 10000


def test_a_sale_on_or_after_the_buy_date_blocks_the_undo(sc, users):  # noqa: F811
    a = users[0]
    fund_id = new_fund(sc, a)
    early = buy(sc, a, fund_id, date="2026-01-10").json()["transaction_id"]
    same_day = buy(sc, a, fund_id, date=SELL_DAY, amount=2000).json()["transaction_id"]
    assert sell(sc, a, "mf", fund_id, quantity=10, price=50).status_code == 201  # on SELL_DAY
    later = buy(sc, a, fund_id, date="2026-02-01", amount=3000).json()["transaction_id"]
    flags = {t["id"]: t["undoable"] for t in transactions(sc, a, fund_id)}
    assert flags[early] is False and flags[same_day] is False and flags[later] is True
    for blocked in (early, same_day):
        r = undo(sc, a, fund_id, blocked)
        assert r.status_code == 409
        assert r.json()["message"] == "Undo the later sale first"
        assert r.json()["description"] == "A sale dated on or after this buy's date may have used these units."
    assert undo(sc, a, fund_id, later).status_code == 200


def test_undo_only_reaches_manual_rows_of_that_holding_and_user(sc, users, auth_engine):  # noqa: F811
    a, _a_id, b, _b_id = users
    fund_id = new_fund(sc, a)
    other_id = add(sc, a, "mf", {**FUND, "platform": "Kuvera", "units": 101, "invested_amount": 4040})
    cas_id = add_txn(auth_engine, fund_id, date(2025, 6, 1), amount=4000, units=100)
    bought = buy(sc, a, fund_id).json()["transaction_id"]
    sip = start(sc, a, mutual_fund_id=None, platform="Kuvera", start_date="2026-03-05").json()
    sip_txn = next(t["id"] for t in transactions(sc, a, sip["mutual_fund_id"]) if t["sip"])
    before = asset(sc, a, "mf", fund_id)
    for who, holding, txn in (
        (a, fund_id, cas_id),  # a CAS row
        (a, sip["mutual_fund_id"], sip_txn),  # a SIP row
        (a, other_id, bought),  # another holding's buy
        (b, fund_id, bought),  # another user
        (a, fund_id, 99999),
    ):
        r = undo(sc, who, holding, txn)
        assert r.status_code == 404, (holding, txn)
        assert r.json()["message"] in ("Record not found", "Holding not found")
    assert asset(sc, a, "mf", fund_id) == before


def test_undo_on_a_closed_fund_or_a_non_fund_is_refused(sc, users):  # noqa: F811
    a = users[0]
    fund_id = new_fund(sc, a)
    txn_id = buy(sc, a, fund_id).json()["transaction_id"]
    assert sell(sc, a, "mf", fund_id, quantity=120, price=50).status_code == 201
    r = undo(sc, a, fund_id, txn_id)
    assert r.status_code == 409 and r.json()["message"] == "Already sold"
    r = sc.delete(f"/api/holdings/stock/{fund_id}/buys/{txn_id}", headers=a)
    assert r.status_code == 404 and r.json()["message"] == "Can't add to this holding"


def test_undo_stops_at_the_floor_a_partial_sale_uses(sc, users, auth_engine):  # noqa: F811
    a = users[0]
    fund_id = new_fund(sc, a)
    txn_id = buy(sc, a, fund_id, amount=1000, nav=50).json()["transaction_id"]  # 20 units
    # 400,000 units left after the undo: the floor is 0.00005 x 400,000 = 20.00 invested.
    for invested, allowed in (("1020.00", True), ("1019.99", False)):
        patch_fund(auth_engine, fund_id, units=D("400020"), invested_amount=D(invested))
        flag = next(t for t in transactions(sc, a, fund_id) if t["id"] == txn_id)["undoable"]
        assert flag is allowed
        if not allowed:
            r = undo(sc, a, fund_id, txn_id)
            assert r.status_code == 409
            assert r.json()["message"] == "Can't undo this buy"
            assert r.json()["description"] == (
                "Removing it would leave the fund with no units or too little invested."
            )
    assert undo(sc, a, fund_id, txn_id).status_code == 409  # still short
    patch_fund(auth_engine, fund_id, invested_amount=D("1020.00"))
    r = undo(sc, a, fund_id, txn_id)
    assert r.status_code == 200
    held = asset(sc, a, "mf", fund_id)
    assert (held["units"], held["invested_amount"]) == (400000, 20)


def test_undo_that_would_leave_no_units_is_refused(sc, users, auth_engine):  # noqa: F811
    a = users[0]
    fund_id = new_fund(sc, a)
    txn_id = buy(sc, a, fund_id).json()["transaction_id"]  # 20 units for 1,000
    patch_fund(auth_engine, fund_id, units=D("20"), invested_amount=D("1000"))
    assert next(t for t in transactions(sc, a, fund_id) if t["id"] == txn_id)["undoable"] is False
    r = undo(sc, a, fund_id, txn_id)
    assert r.status_code == 409 and r.json()["message"] == "Can't undo this buy"


def test_only_manual_rows_are_ever_undoable(sc, users, auth_engine):  # noqa: F811
    a = users[0]
    fund_id = new_fund(sc, a)
    add_txn(auth_engine, fund_id, date(2025, 6, 1), amount=4000, units=100)
    assert [t["undoable"] for t in transactions(sc, a, fund_id)] == [False]


def test_undoing_an_already_undone_buy_is_not_found(sc, users):  # noqa: F811
    a = users[0]
    fund_id = new_fund(sc, a)
    txn_id = buy(sc, a, fund_id).json()["transaction_id"]
    assert undo(sc, a, fund_id, txn_id).status_code == 200
    r = undo(sc, a, fund_id, txn_id)
    assert r.status_code == 404 and r.json()["message"] == "Record not found"


# --- too small an amount for the units ----------------------------------------------------------


def test_an_amount_too_small_for_the_units_is_refused_and_nothing_is_written(sc, users, auth_engine):  # noqa: F811
    a = users[0]
    fund_id = new_fund(sc, a)
    patch_fund(auth_engine, fund_id, units=D("1"), invested_amount=D("0.01"))
    before = transactions(sc, a, fund_id)
    # 400,000 units after the buy: the floor is 0.00005 x 400,000 = 20.00 invested.
    r = buy(sc, a, fund_id, amount=19.98, nav=50, units=399999)  # 19.99 invested: just below
    assert r.status_code == 422
    assert errors(r) == (("amount",), "Amount is too small for this many units")
    held = asset(sc, a, "mf", fund_id)
    assert (held["units"], held["invested_amount"]) == (1, 0.01)
    assert transactions(sc, a, fund_id) == before
    with sessionmaker(bind=auth_engine)() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(MFTransaction)) == 0
    r = buy(sc, a, fund_id, amount=19.99, nav=50, units=399999)  # 20.00 invested: allowed
    assert r.status_code == 201, r.json()
    held = asset(sc, a, "mf", fund_id)
    assert (held["units"], held["invested_amount"]) == (400000, 20)


# --- capital gains lots ---------------------------------------------------------------------------


def test_capital_gains_lots_include_the_buy(sc, users, auth_engine, monkeypatch):  # noqa: F811
    from app.routers import analytics_gains
    from tests.test_capital_gains_api import _FixedDate

    monkeypatch.setattr(analytics_gains, "date", _FixedDate)
    with auth_engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE IF NOT EXISTS bond_master (id INTEGER PRIMARY KEY, bond_type VARCHAR,"
                " issuer VARCHAR, face_value NUMERIC, coupon_rate NUMERIC, coupon_type VARCHAR,"
                " interest_frequency VARCHAR, issue_date DATE, issue_price NUMERIC,"
                " maturity_date DATE)"
            )
        )
    a = users[0]
    fund_id = new_fund(sc, a)  # 100 units for 4,000 on 2025-06-01
    assert buy(sc, a, fund_id, amount=3000, nav=150).status_code == 201  # 20 units on 2026-01-10
    sold = sell(sc, a, "mf", fund_id, quantity=110, price=50)  # sold on 2026-01-15
    assert sold.status_code == 201, sold.json()
    r = sc.get("/api/analytics/capital-gains?fy=2025", headers=a)
    assert r.status_code == 200, r.json()
    [sale] = [s for s in r.json()["sales"] if s["asset_type"] == "mf"]
    first, second = sale["lots"]
    assert (first["bought_on"], first["quantity"], first["cost"]) == ("2025-06-01", 100, 4000)
    assert (second["bought_on"], second["quantity"], second["cost"]) == (BUY_DAY, 10, 1500)


# --- property: the totals are the sums over the transactions --------------------------------------


ops_st = st.lists(
    st.one_of(
        st.tuples(
            st.just("buy"), st.integers(0, 280), st.integers(100, 5_000_000).map(lambda c: D(c) / 100),
            st.integers(100, 100_000).map(lambda n: D(n) / 100),
        ),
        st.tuples(st.just("undo"), st.integers(0, 20), st.just(None), st.just(None)),
    ),
    max_size=14,
)


@given(ops_st)
def test_totals_always_equal_the_transaction_sums(ops):
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(
        engine, tables=[MutualFund.__table__, MFTransaction.__table__, HoldingExit.__table__]
    )
    today = date(2026, 3, 10)
    with Session(engine) as db:
        fund = MutualFund(
            user_id=1, scheme_name="Fund A", category="equity", units=D("100"), avg_nav=D("40"),
            invested_amount=D("4000"), purchase_date=date(2025, 6, 1),
        )  # fmt: skip
        db.add(fund)
        db.flush()
        manual: list[int] = []
        for kind, a, b, c in ops:
            try:
                if kind == "buy":
                    day = date.fromordinal(date(2025, 6, 1).toordinal() + a)
                    body = BuyBody(date=day, amount=b, nav=c)
                    manual.append(buys_service.record_mf_buy(db, fund, body, today, True).transaction.id)
                elif manual:
                    txn_id = manual[a % len(manual)]
                    buys_service.undo_mf_buy(db, fund, txn_id)
                    manual.remove(txn_id)
            except (ExitConflict, ExitError):
                continue
            rows = db.scalars(sa.select(MFTransaction).where(MFTransaction.mutual_fund_id == fund.id)).all()
            if not rows:
                continue
            units = sum((D(str(t.units)) for t in rows), D(0))
            invested = sum((D(str(t.amount)) for t in rows), D(0))
            assert D(str(fund.units)) == units
            assert D(str(fund.invested_amount)) == invested
            assert D(str(fund.avg_nav)) == (invested / units).quantize(D("0.0001"))
            assert fund.purchase_date == date(2025, 6, 1)
    engine.dispose()

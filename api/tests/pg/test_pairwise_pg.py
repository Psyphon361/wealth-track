"""Pairwise concurrency (marker pg): every pair of actions that share a row, run A-held / B-waiting.

Oracle: the concurrent run must end in the state AND with the response codes of ONE serial order
(A then B, or B then A), each computed on its own freshly truncated database. See helpers_pairwise.py.
Pairs are listed in PAIRS; the first action of a pair is the one held inside its critical section.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.services import exits as exits_service
from app.services import fundings
from app.services import sip as sip_service
from tests.pg.helpers_pairwise import After, BeforeCommit, Pair, run_pair
from tests.pg.helpers_t3 import FD, FUND, STOCK, cash_body, stock_body
from tests.pg.test_concurrency_pg import run_purge

pytestmark = pytest.mark.pg

NAV_NOT_FETCH = lambda args, kwargs: kwargs.get("fetch") is False  # noqa: E731


# --- worlds ---------------------------------------------------------------------------------------


def w_stock(w):
    """Cash 1000 and a stock of 100."""
    return SimpleNamespace(cash=w.add_cash(balance=1000), stock=w.add("stock", STOCK))


def w_part_sold(w):
    """Stock with 40 sold into cash (exit `first`), 60 left."""
    cash = w.add_cash(balance=0)
    stock = w.add("stock", STOCK)
    first = w.sell_stock(stock, 40, 80, to_cash=cash)
    assert first.status_code == 201, first.text
    return SimpleNamespace(cash=cash, stock=stock, exit_id=first.json()["id"])


def w_sold(w):
    """Stock fully sold into cash 100000 (exit `exit_id`)."""
    cash = w.add_cash(balance=100000)
    stock = w.add("stock", STOCK)
    sale = w.sell_stock(stock, 100, 80, to_cash=cash)
    assert sale.status_code == 201, sale.text
    return SimpleNamespace(cash=cash, stock=stock, exit_id=sale.json()["id"])


def w_funded(w):
    """Cash 100000 and a stock paid from it (5000)."""
    cash = w.add_cash(balance=100000)
    r = w.add_paid("stock", stock_body("Funded Ltd", 100), cash)
    assert r.status_code == 201, r.text
    return SimpleNamespace(cash=cash, stock=r.json()["id"])


def w_funded_deleted(w):
    ctx = w_funded(w)
    assert w.delete("stock", ctx.stock).status_code == 200
    return ctx


def w_deleted_old(w):
    ctx = w_funded_deleted(w)
    with w.engine.begin() as conn:
        conn.execute(text("UPDATE stocks SET deleted_at = now() - interval '40 days'"))
    return ctx


def w_cash(w):
    return SimpleNamespace(cash=w.add_cash(balance=100000))


def w_fd(w):
    cash = w.add_cash(balance=0)
    return SimpleNamespace(cash=cash, fd=w.add("fd", FD), dest={"kind": "cash_existing", "cash_id": cash})


def w_fund(w):
    w.seed_funds()
    fund = w.add("mf", FUND)
    return SimpleNamespace(fund=fund, sip=w.add_sip(fund))


def w_fund_sold(w):
    ctx = w_fund(w)
    assert w.sell("mf", ctx.fund, quantity=100, price=60, date="2026-03-10").status_code == 201
    return ctx


# --- actions --------------------------------------------------------------------------------------


def sell(n):
    return lambda w, c: w.sell_stock(c.stock, n, 80, to_cash=c.cash)


def sell_mf(w, c):
    return w.sell("mf", c.fund, quantity=10, price=60, date="2026-03-10")


def post_due(w, c):
    return w.post_due()


def undo(w, c):
    return w.undo(c.exit_id)


def reinvest(w, c):
    return w.add_paid("stock", stock_body("Reinvest Ltd", 10), c.cash, from_exit_id=c.exit_id)


def paid_from(w, c):
    return w.add_paid("stock", stock_body("Second Ltd", 100), c.cash)


def delete_stock(w, c):
    return w.delete("stock", c.stock)


def restore_stock(w, c):
    return w.restore("stock", c.stock)


def put_stock(w, c):
    return w.put("stock", c.stock, stock_body("Renamed Ltd", 100))


def put_cost_up(w, c):
    """Raise the funded stock's cost from 5,000 to 10,000 (moves 5,000 more off the account)."""
    return w.put("stock", c.stock, stock_body("Funded Ltd", 200))


def cash_put(w, c):
    return w.put("cash", c.cash, cash_body(balance=1000))


def cash_delete(w, c):
    return w.delete("cash", c.cash)


def settle(w, c):
    return w.settle("fd", c.fd, c.dest)


def delete_fd(w, c):
    return w.delete("fd", c.fd)


def purge(w, c):
    return run_purge(w)


REC_SALE = After(exits_service, "record_sale")
REC_SETTLE = After(exits_service, "record_settlement")
UNDO = After(exits_service, "undo_exit")
REFUND = After(fundings, "refund")
RESTORE = After(fundings, "restore")
PLAN = After(fundings, "plan")
PLAN_EDIT = After(fundings, "plan_edit")

PAIRS = [
    # sell / settle / undo on one holding or exit
    Pair("sell part vs sell part", w_stock, sell(60), sell(60), REC_SALE),
    Pair("sell all vs sell all", w_stock, sell(100), sell(100), REC_SALE),
    Pair("sell part vs sell fits", w_stock, sell(30), sell(50), REC_SALE),
    Pair("settle vs settle", w_fd, settle, settle, REC_SETTLE),
    Pair("settle vs delete", w_fd, settle, delete_fd, REC_SETTLE),
    Pair("sell vs undo earlier sale", w_part_sold, sell(30), undo, REC_SALE),
    Pair("undo vs sell", w_part_sold, undo, sell(30), UNDO),
    Pair("undo vs undo", w_sold, undo, undo, UNDO),
    Pair("undo vs reinvest", w_sold, undo, reinvest, UNDO),
    Pair("reinvest vs undo", w_sold, reinvest, undo, PLAN),
    Pair("undo vs delete", w_sold, undo, delete_stock, UNDO),
    # delete / restore / purge on one holding
    Pair("sell vs delete", w_stock, sell(40), delete_stock, REC_SALE),
    Pair("delete vs sell", w_stock, delete_stock, sell(40), REFUND),
    Pair("delete vs delete", w_funded, delete_stock, delete_stock, REFUND),
    Pair("delete vs restore", w_funded, delete_stock, restore_stock, REFUND, blocks=False),
    Pair("restore vs delete", w_funded_deleted, restore_stock, delete_stock, RESTORE, blocks=False),
    Pair("restore vs restore", w_funded_deleted, restore_stock, restore_stock, RESTORE),
    Pair("restore vs purge", w_deleted_old, restore_stock, purge, RESTORE),
    Pair("purge vs restore", w_deleted_old, purge, restore_stock, BeforeCommit("world")),
    # edit a holding
    Pair("edit vs sell", w_stock, put_stock, sell(40), BeforeCommit()),
    Pair("sell vs edit", w_stock, sell(40), put_stock, REC_SALE),
    Pair("edit vs delete", w_stock, put_stock, delete_stock, BeforeCommit()),
    # edit the cost of a holding paid from an account (holding, funding row, then the account)
    Pair("cost edit vs delete", w_funded, put_cost_up, delete_stock, PLAN_EDIT),
    Pair("delete vs cost edit", w_funded, delete_stock, put_cost_up, REFUND),
    Pair("cost edit vs paid from", w_funded, put_cost_up, paid_from, PLAN_EDIT),
    Pair("paid from vs cost edit", w_funded, paid_from, put_cost_up, PLAN),
    Pair("cost edit vs cash edit", w_funded, put_cost_up, cash_put, PLAN_EDIT, ledger=False),
    Pair("cash edit vs cost edit", w_funded, cash_put, put_cost_up, BeforeCommit(), ledger=False),
    Pair("cost edit vs cash delete", w_funded, put_cost_up, cash_delete, PLAN_EDIT),
    Pair("cash delete vs cost edit", w_funded, cash_delete, put_cost_up, BeforeCommit()),
    # one cash account
    Pair("cash edit vs paid from", w_cash, cash_put, paid_from, BeforeCommit(), ledger=False),
    Pair("paid from vs cash edit", w_cash, paid_from, cash_put, PLAN, ledger=False),
    Pair("cash edit vs cash delete", w_cash, cash_put, cash_delete, BeforeCommit(), ledger=False),
    Pair("cash delete vs sell into it", w_stock, cash_delete, sell(100), REFUND),
    Pair("sell into cash vs cash delete", w_stock, sell(100), cash_delete, REC_SALE),
    # SIP posting
    Pair("sell fund vs post due", w_fund, sell_mf, post_due, REC_SALE),
    Pair("post due vs sell fund", w_fund, post_due, sell_mf, After(sip_service, "nav_for_due", NAV_NOT_FETCH)),
    Pair("post due vs post due", w_fund_sold, post_due, post_due, After(sip_service, "_active_target")),
]


@pytest.mark.parametrize("pair", PAIRS, ids=[p.name for p in PAIRS])
def test_pair_matches_a_serial_order(pg_app, monkeypatch, pair):
    run_pair(pg_app, monkeypatch, pair)

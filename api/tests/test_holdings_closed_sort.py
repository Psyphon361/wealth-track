"""Closed tab sorting of GET /api/holdings/{type}: closed_on, received, realised_gain, defaults."""

from app.routers.holdings import _sort_value
from tests.test_exits_api import FD, STOCK, add, sell, settle
from tests.test_scoping import client, users  # noqa: F401  (fixtures)


def ids(c, headers, slug, query):
    r = c.get(f"/api/holdings/{slug}?{query}", headers=headers)
    assert r.status_code == 200, r.json()
    return [i["id"] for i in r.json()["items"]]


def sold_stocks(c, headers):
    """Three sold stocks: (id, sold on, received, realised gain)."""
    out = {}
    for name, day, price in (
        ("Alpha Ltd", "2026-01-10", 80),  # 8000 received, +3000
        ("Beta Ltd", "2026-02-01", 40),  # 4000 received, -1000
        ("Gamma Ltd", "2025-12-01", 60),  # 6000 received, +1000
    ):
        stock_id = add(c, headers, "stock", {**STOCK, "name": name})
        assert sell(c, headers, "stock", stock_id, quantity=100, price=price, date=day).status_code == 201
        out[name] = stock_id
    return out


def test_sort_value_derives_the_closed_keys():
    exit_ = {"date": "2026-01-10", "amount": 8000, "cost": 5000}
    sold = {"exit": exit_, "closed_on": "2026-01-11", "maturity_date": "2020-01-01"}
    assert _sort_value(sold, "closed_on", set()) == "2026-01-10"
    assert _sort_value(sold, "received", set()) == 8000
    assert _sort_value(sold, "realised_gain", set()) == 3000

    closed = {"exit": None, "closed_on": "2026-01-11", "maturity_date": "2020-01-01"}
    assert _sort_value(closed, "closed_on", set()) == "2026-01-11"
    matured = {"exit": None, "closed_on": None, "maturity_date": "2020-01-01", "maturity_amount": 1234.5}
    assert _sort_value(matured, "closed_on", set()) == "2020-01-01"
    assert _sort_value(matured, "received", set()) == 1234.5
    assert _sort_value(matured, "realised_gain", set()) is None

    bare = {"exit": None, "closed_on": None, "maturity_date": None, "maturity_amount": None}
    assert _sort_value(bare, "closed_on", set()) is None
    assert _sort_value(bare, "received", set()) == 0


def test_closed_tab_defaults_to_newest_closed_first(client, users):
    a = users[0]
    s = sold_stocks(client, a)
    newest_first = [s["Beta Ltd"], s["Alpha Ltd"], s["Gamma Ltd"]]
    assert ids(client, a, "stock", "status=closed") == newest_first
    assert ids(client, a, "stock", "status=closed&sort=closed_on") == newest_first
    assert ids(client, a, "stock", "status=closed&sort=closed_on&dir=asc") == newest_first[::-1]
    # An explicit sort still wins over the Closed default.
    by_name = ids(client, a, "stock", "status=closed&sort=name&dir=asc")
    assert by_name == [s["Alpha Ltd"], s["Beta Ltd"], s["Gamma Ltd"]]


def test_closed_tab_sorts_by_received_and_realised_gain(client, users):
    a = users[0]
    s = sold_stocks(client, a)
    alpha, beta, gamma = s["Alpha Ltd"], s["Beta Ltd"], s["Gamma Ltd"]
    assert ids(client, a, "stock", "status=closed&sort=received") == [alpha, gamma, beta]
    assert ids(client, a, "stock", "status=closed&sort=received&dir=asc") == [beta, gamma, alpha]
    assert ids(client, a, "stock", "status=closed&sort=realised_gain") == [alpha, gamma, beta]
    assert ids(client, a, "stock", "status=closed&sort=realised_gain&dir=asc") == [beta, gamma, alpha]


def test_rows_without_an_exit_sort_last_for_realised_gain_either_way(client, users):
    a = users[0]
    open_fd = add(client, a, "fd", FD)  # matured on 2025-01-01, not settled yet
    settled_fd = add(client, a, "fd", {**FD, "bank": "Settled Bank", "principal": 50000})
    assert settle(client, a, "fd", settled_fd).status_code == 201

    for direction in ("asc", "desc"):
        got = ids(client, a, "fd", f"status=closed&sort=realised_gain&dir={direction}")
        assert got == [settled_fd, open_fd], direction
    # Unsettled maturity counts as received (its maturity amount) and closes on its maturity date.
    assert ids(client, a, "fd", "status=closed&sort=received") == [open_fd, settled_fd]


def test_other_statuses_keep_their_default_sort(client, users):
    a = users[0]
    small = add(client, a, "stock", {**STOCK, "name": "Small Ltd", "quantity": 1})
    big = add(client, a, "stock", {**STOCK, "name": "Big Ltd", "quantity": 500})
    sold = add(client, a, "stock", {**STOCK, "name": "Sold Ltd"})
    assert sell(client, a, "stock", sold, quantity=100, price=80).status_code == 201
    assert ids(client, a, "stock", "status=active") == [big, small]
    assert ids(client, a, "stock", "status=active&dir=asc") == [small, big]
    assert ids(client, a, "stock", "status=sold") == [sold]
    assert ids(client, a, "stock", "")[0] == big  # unfiltered stays on current value

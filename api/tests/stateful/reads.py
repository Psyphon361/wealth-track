"""The read-side oracle of the money machine: dashboard, portfolio, net worth and the grids.

After a step the machine reads GET /api/dashboard, /api/portfolio, /api/networth/history?range=1m
and GET /api/holdings/{slug} (every page) for each type it has created, and checks (SPEC §5, §9):

 (a) WHICH holdings are counted and at what invested amount, against the machine's model: deleted
     holdings are in no read; sold-out, settled and matured holdings are listed with a status other
     than "active" and are in no total; a partly sold one counts at its remaining cost.
 (b) current values AGREE ACROSS endpoints only (the model never recomputes a current value):
     each grid row = the portfolio row; grid summary = sum of its active rows = the portfolio group
     total = the dashboard per-type figure; dashboard total = sum of its types = the net worth
     history's last point (today). The history's last point is the dashboard total by construction
     (build_history overwrites it), so that last comparison is documented as trivially true; the
     drifts hidden by it are pinned in tests/test_networth_today_agreement.py.
 (c) the cash total is the model's live balances, on every endpoint.

Tolerance: n x 0.005 for n summed rows (each row is rounded to the cent on its own).
"""

from __future__ import annotations

import os
from decimal import Decimal

from tests.stateful.world import d

HALF_CENT = Decimal("0.005")
ALL_SLUGS = ("fd", "rd", "stock", "bond", "mf", "nps", "gold", "cash", "pf", "other")
GRID_SLUGS = ("fd", "stock", "bond", "mf", "gold", "other", "cash")
OTHER_CURRENT = Decimal("80000.00")  # the machine's Other holdings: current value 80000
# Run the full check after every Nth invariant run, and always at the end of a run (teardown). One
# check is ~30 ms (about 10 requests); at 1 the SQLite machine took 85 s, at 5 it stays near 25 s.
# STATEFUL_READ_EVERY=1 checks after every step (local hunts).
EVERY = int(os.environ.get("STATEFUL_READ_EVERY", "5"))


def counted(h) -> bool:
    """Is the holding in the active totals? (sold-out, settled and matured ones are not)"""
    return h.live and not h.closed and not h.settled and not (h.slug in ("fd", "bond") and h.matured)


def model_invested(h) -> Decimal:
    if h.slug == "fd":
        return h.invested0
    if h.slug == "stock":
        return h.inv()
    if h.slug == "other":
        return h.invested if h.invested is not None else OTHER_CURRENT
    return h.invested


def near(m, what: str, got, want, n: int = 1) -> None:
    if abs(d(got) - d(want)) > max(n, 1) * HALF_CENT:
        m.fail(f"read oracle: {what}: {got} != {want} (tolerance {max(n, 1)} x 0.005)")


def get(m, url: str, **params):
    r = m.h.call("GET", url, params=params or None)
    if r.status_code != 200:
        m.fail(f"read oracle: GET {url} {params or ''} -> {r.status_code}: {r.text[:300]}")
    return r.json()


def grid(m, slug: str) -> tuple[list[dict], dict]:
    """Every row of GET /api/holdings/{slug} (all pages, all statuses) and the summary."""
    rows: list[dict] = []
    page, summary = 1, {}
    while True:
        body = get(m, f"/api/holdings/{slug}", page=page)
        rows += body["items"]
        summary = body["summary"]
        if page >= body["page_count"]:
            break
        page += 1
    ids = [r["id"] for r in rows]
    if len(ids) != len(set(ids)) or len(rows) != body["total"]:
        m.fail(f"read oracle: {slug} grid pages repeat or lose rows: {len(rows)} rows, total {body['total']}, ids {ids}")
    return rows, summary


def check_user2(m) -> None:
    """The second user's reads count only their own holdings: their dashboard and portfolio match the
    model's list of what they added (cash accounts, Other and stock holdings, none matured or sold). User 1's
    totals not including these rows is checked by the main oracle (the model has none of them)."""
    h = m.h
    dash = h.call("GET", "/api/dashboard", as_user=2)
    portfolio = h.call("GET", "/api/portfolio", as_user=2)
    if dash.status_code != 200 or portfolio.status_code != 200:
        m.fail(f"read oracle: user 2 dashboard/portfolio -> {dash.status_code}/{portfolio.status_code}")
    by_type = {r["type"]: r for r in dash.json()["by_type"]}
    groups = {g["type"]: g for g in portfolio.json()["groups"]}
    total = Decimal(0)
    for slug in ALL_SLUGS:
        if slug == "cash":
            want_ids = set(m.u2cash)
            invested = sum(m.u2cash.values(), Decimal(0))
        else:
            mine = [x for x in m.u2hold if x[0] == slug]
            want_ids = {x[1] for x in mine}
            invested = sum((x[2] for x in mine), Decimal(0))
        n = len(want_ids)
        if {i["id"] for i in groups[slug]["items"]} != want_ids:
            m.fail(f"read oracle: user 2 portfolio {slug} lists {sorted(i['id'] for i in groups[slug]['items'])}, own {sorted(want_ids)}")
        row = by_type[slug]
        if row["count"] != n:
            m.fail(f"read oracle: user 2 dashboard {slug} count {row['count']} != {n}")
        near(m, f"user 2 dashboard {slug} invested", row["invested"], invested, n)
        total += invested
    near(m, "user 2 dashboard total invested", dash.json()["total_invested"], total, len(ALL_SLUGS))


def check_reads(m, force: bool = False) -> None:
    from tests.stateful.machine import TALLY

    m.steps += 1
    if not force and m.steps % EVERY:
        return
    m.h.assert_safe()
    TALLY["read oracle runs"] += 1
    check_user2(m)

    portfolio = {g["type"]: g for g in get(m, "/api/portfolio")["groups"]}
    dash = get(m, "/api/dashboard")
    by_type = {r["type"]: r for r in dash["by_type"]}
    history = get(m, "/api/networth/history", range="1m")

    sum_invested = Decimal(0)
    sum_current = Decimal(0)
    unsettled_model = set()
    for slug in ALL_SLUGS:
        group = portfolio[slug]
        row = by_type[slug]
        if slug == "cash":
            live = [c for c in m.cash.values() if c.live]
            want_ids = {c.id for c in live}
            active_ids = want_ids  # an account is always counted
            want_invested = sum((c.bal for c in live), Decimal(0))
        else:
            live = [h for h in m.holds.values() if h.slug == slug and h.live]
            want_ids = {h.id for h in live}
            active_ids = {h.id for h in live if counted(h)}
            want_invested = sum((model_invested(h) for h in live if counted(h)), Decimal(0))
            unsettled_model |= {
                (slug, h.id) for h in live if slug in ("fd", "bond") and h.matured and not h.settled
            }
        n = len(active_ids)

        # (a) the portfolio lists exactly the live holdings; the active ones at the model's invested amount
        items = {i["id"]: i for i in group["items"]}
        if set(items) != want_ids:
            m.fail(f"read oracle: portfolio {slug} lists {sorted(items)}, model live {sorted(want_ids)}")
        for item in items.values():
            is_active = item["status"] == "active"
            if is_active != (item["id"] in active_ids):
                m.fail(f"read oracle: {slug} {item['id']}: status {item['status']!r}, model counted={item['id'] in active_ids}")
        if slug == "cash":
            for c in live:
                near(m, f"cash {c.id} balance in the portfolio", items[c.id]["current_value"], c.bal)
        else:
            for h in live:
                if counted(h):
                    near(m, f"{slug} {h.id} invested in the portfolio", items[h.id]["invested"], model_invested(h))
        active_items = [i for i in group["items"] if i["status"] == "active"]
        near(m, f"{slug} portfolio invested total", group["totals"]["invested"], want_invested, n)
        if group["count"] != n:
            m.fail(f"read oracle: {slug} portfolio count {group['count']} != model {n}")

        # (b) one valuation everywhere: sum of rows = group total = dashboard row = grid summary
        current = sum((d(i["current_value"]) for i in active_items), Decimal(0))
        near(m, f"{slug} portfolio current total vs its rows", group["totals"]["current_value"], current, n)
        near(m, f"{slug} dashboard invested vs the model", row["invested"], want_invested, n)
        near(m, f"{slug} dashboard current vs portfolio", row["current"], group["totals"]["current_value"], n)
        if row["count"] != n or row["closed_count"] != len(want_ids) - n:
            m.fail(f"read oracle: {slug} dashboard count/closed {row['count']}/{row['closed_count']} != {n}/{len(want_ids) - n}")
        if slug == "cash":  # (c) cash is worth its balance, on every endpoint
            near(m, "cash dashboard current vs the live balances", row["current"], want_invested, n)
        sum_invested += d(row["invested"])
        sum_current += d(row["current"])

        # the grid: same rows, same valuation, same totals
        if slug in GRID_SLUGS and (m.cash if slug == "cash" else any(k[0] == slug for k in m.holds)):
            rows, summary = grid(m, slug)
            if {r["id"] for r in rows} != want_ids:
                m.fail(f"read oracle: {slug} grid lists {sorted(r['id'] for r in rows)}, model live {sorted(want_ids)}")
            for r in rows:
                near(m, f"{slug} {r['id']} grid vs portfolio current", r["current_value"], items[r["id"]]["current_value"])
                near(m, f"{slug} {r['id']} grid vs portfolio invested", r["invested"], items[r["id"]]["invested"])
                if r["status"] != items[r["id"]]["status"]:
                    m.fail(f"read oracle: {slug} {r['id']} grid status {r['status']} != portfolio {items[r['id']]['status']}")
            near(m, f"{slug} grid summary current vs portfolio", summary["current_value"], group["totals"]["current_value"], n)
            near(m, f"{slug} grid summary invested vs the model", summary["invested"], want_invested, n)
            if summary["count"] != n:
                m.fail(f"read oracle: {slug} grid count {summary['count']} != model {n}")
            priced = [i for i in active_items if slug in ("stock", "mf", "gold") and d(i["current_value"]) != d(i["invested"])]
            if priced:
                TALLY[f"read: {slug} valued away from invested"] += 1

    # the dashboard totals are the sum of the types, and the unsettled card lists the matured ones
    near(m, "dashboard total invested vs its types", dash["total_invested"], sum_invested, len(ALL_SLUGS))
    near(m, "dashboard total current vs its types", dash["total_current"], sum_current, len(ALL_SLUGS))
    listed = {(i["type"], i["id"]) for i in dash["unsettled"]["items"]}
    if listed != unsettled_model:
        m.fail(f"read oracle: dashboard unsettled {sorted(listed)} != model matured and unsettled {sorted(unsettled_model)}")

    # net worth: today's point is the dashboard total (by construction: see the module docstring)
    points = history["points"]
    if points:
        last = points[-1]
        if last["date"] != m.h.today.isoformat():
            m.fail(f"read oracle: net worth ends on {last['date']}, the clock is {m.h.today}")
        near(m, "net worth today invested vs dashboard", last["invested"], dash["total_invested"])
        near(m, "net worth today current vs dashboard", last["current"], dash["total_current"])
    elif d(dash["total_current"]) != 0 or d(dash["total_invested"]) != 0:
        m.fail(f"read oracle: empty net worth history but dashboard totals {dash['total_invested']}/{dash['total_current']}")

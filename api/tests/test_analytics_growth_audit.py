"""Audit of net worth Growth (services/analytics_growth.py). Expected figures are worked by hand in
the comments, independently of the code. `today` is 2026-11-03 unless a test says otherwise."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.services import analytics_growth as g

D = Decimal
TODAY = date(2026, 11, 3)


def _pt(d, invested, current):
    return {"date": d.isoformat(), "invested": D(str(invested)), "current": D(str(current))}


# Month-end points plus today. (date, invested, current)
SERIES = [
    (date(2025, 10, 31), 100000, 100000),
    (date(2025, 11, 30), 110000, 112000),
    (date(2025, 12, 31), 120000, 125000),
    (date(2026, 1, 31), 120000, 121000),
    (date(2026, 2, 28), 130000, 131000),
    (date(2026, 3, 31), 140000, 150000),
    (date(2026, 4, 30), 140000, 148000),
    (date(2026, 5, 31), 150000, 160000),
    (date(2026, 6, 30), 150000, 165000),
    (date(2026, 7, 31), 160000, 175000),
    (date(2026, 8, 31), 160000, 172000),
    (date(2026, 9, 30), 170000, 185000),
    (date(2026, 10, 31), 180000, 200000),
    (date(2026, 11, 3), 180000, 205000),
]
POINTS = [_pt(*row) for row in SERIES]


def _row(x):
    return (x["start_value"], x["end_value"], x["new_money"], x["growth"], x["change"])


def test_hand_computed_periods():
    result = g.build_growth(POINTS, TODAY)
    p = {x["key"]: x for x in result["periods"]}
    # (start, end, new_money, growth, change); growth = change - new_money
    # this_month: start 31 Oct 200000/180000, end 205000/180000 -> change 5000, nm 0, g 5000, 5000/200000 = 2.50%
    assert _row(p["this_month"]) == (D(200000), D(205000), D(0), D(5000), D(5000))
    assert p["this_month"]["growth_pct"] == D("2.50")
    # last_month: 30 Sep 185000/170000 -> 31 Oct 200000/180000: change 15000, nm 10000, g 5000, 5000/185000 = 2.7027%
    assert _row(p["last_month"]) == (D(185000), D(200000), D(10000), D(5000), D(15000))
    assert p["last_month"]["growth_pct"] == D("2.70")
    # fy: 31 Mar 2026 150000/140000 -> 205000/180000: change 55000, nm 40000, g 15000, 10%
    assert _row(p["fy"]) == (D(150000), D(205000), D(40000), D(15000), D(55000))
    assert p["fy"]["growth_pct"] == D("10.00")
    # ytd: 31 Dec 2025 125000/120000 -> change 80000, nm 60000, g 20000, 16%
    assert _row(p["ytd"]) == (D(125000), D(205000), D(60000), D(20000), D(80000))
    assert p["ytd"]["growth_pct"] == D("16.00")
    # 1y: 3 Nov 2025 -> last point on/before is 31 Oct 2025 100000/100000: change 105000, nm 80000, g 25000, 25%
    assert _row(p["1y"]) == (D(100000), D(205000), D(80000), D(25000), D(105000))
    assert p["1y"]["growth_pct"] == D("25.00")


def test_hand_computed_months():
    months = g.build_growth(POINTS, TODAY)["months"]
    # month -> (start, end, new_money, growth, change)
    expected = {
        "2025-12": (112000, 125000, 10000, 3000, 13000),
        "2026-01": (125000, 121000, 0, -4000, -4000),
        "2026-02": (121000, 131000, 10000, 0, 10000),
        "2026-03": (131000, 150000, 10000, 9000, 19000),
        "2026-04": (150000, 148000, 0, -2000, -2000),
        "2026-05": (148000, 160000, 10000, 2000, 12000),
        "2026-06": (160000, 165000, 0, 5000, 5000),
        "2026-07": (165000, 175000, 10000, 0, 10000),
        "2026-08": (175000, 172000, 0, -3000, -3000),
        "2026-09": (172000, 185000, 10000, 3000, 13000),
        "2026-10": (185000, 200000, 10000, 5000, 15000),
        "2026-11": (200000, 205000, 0, 5000, 5000),
    }
    assert [m["month"] for m in months] == list(expected)
    for m in months:
        assert _row(m) == tuple(D(v) for v in expected[m["month"]]), m["month"]
    # Sum of changes: 13-4+10+19-2+12+5+10-3+13+15+5 = 93000 = 205000 - 112000
    assert sum(m["change"] for m in months) == D(93000)


# --- Invariants over many dates ----------------------------------------------------------------


def _daily_points(start, end):
    pts, d, i = [], start, 0
    while d <= end:
        invested = D(1000) + D(i) * D("37.25") + D(i // 30) * D(500)
        current = invested + D((i * 7919) % 2001 - 700) + D(i) * D("1.15")
        pts.append(_pt(d, invested, current))
        d += timedelta(days=1)
        i += 1
    return pts


DAILY = _daily_points(date(2024, 12, 1), date(2029, 1, 31))

_all_days = []
for _y in (2027, 2028):
    _d = date(_y, 1, 1)
    while _d.year == _y:
        _all_days.append(_d)
        _d += timedelta(days=1)


def _expected_fy(today):
    return date(today.year if today.month >= 4 else today.year - 1, 3, 31)


@pytest.mark.parametrize("today", _all_days, ids=lambda d: d.isoformat())
def test_invariants(today):
    result = g.build_growth(DAILY, today)
    periods, months = result["periods"], result["months"]
    by = {p["key"]: p for p in periods}
    for r in periods + months:
        assert r["change"] == r["new_money"] + r["growth"]
        assert r["change"] == r["end_value"] - r["start_value"]
    assert len(months) == 12
    # telescoping
    assert sum(m["change"] for m in months) == months[-1]["end_value"] - months[0]["start_value"]
    assert months[-1]["end_value"] == by["this_month"]["end_value"]
    assert by["this_month"]["start_value"] == months[-1]["start_value"]
    assert by["this_month"]["change"] == months[-1]["change"]
    assert by["this_month"]["new_money"] == months[-1]["new_money"]
    for k in ("start_value", "end_value", "new_money", "growth", "change"):
        assert by["last_month"][k] == months[-2][k]
    # dates
    assert by["this_month"]["start_date"] == today.replace(day=1) - timedelta(days=1)
    assert by["last_month"]["end_date"] == today.replace(day=1) - timedelta(days=1)
    assert by["last_month"]["start_date"] == (today.replace(day=1) - timedelta(days=1)).replace(day=1) - timedelta(days=1)
    assert by["fy"]["start_date"] == _expected_fy(today)
    assert by["ytd"]["start_date"] == date(today.year - 1, 12, 31)
    assert by["1y"]["start_date"].year == today.year - 1
    assert (today - by["1y"]["start_date"]).days in (365, 366)
    for p in periods:
        assert p["start_date"] < p["end_date"]
        pct = p["growth_pct"]
        if p["start_value"] == 0:
            assert pct is None
        elif p["growth"] > 0:
            assert pct >= 0
        elif p["growth"] < 0:
            assert pct <= 0
    # sum of new money across months equals invested(end) - invested(oldest start)
    lookup = g._Lookup(DAILY)
    oldest_start = months[0]
    first = today.replace(day=1) - g.relativedelta(months=11)
    s_cur, s_inv = lookup.at(first - timedelta(days=1))
    e_cur, e_inv = lookup.at(today)
    assert sum(m["new_money"] for m in months) == e_inv - s_inv
    assert oldest_start["start_value"] == s_cur


def test_no_point_before_start_gives_zero_start():
    pts = [_pt(date(2026, 11, 1), 500, 520), _pt(TODAY, 600, 650)]
    p = {x["key"]: x for x in g.build_growth(pts, TODAY)["periods"]}
    for k in ("fy", "ytd", "1y", "this_month", "last_month"):
        assert p[k]["start_value"] == 0 and p[k]["growth_pct"] is None
    assert p["ytd"]["new_money"] == 600 and p["ytd"]["growth"] == 50
    # last month ends 31 Oct, before any point: everything zero
    assert _row(p["last_month"]) == (D(0),) * 5


# --- Edge data -----------------------------------------------------------------------------------


def test_empty_and_single_point():
    empty = g.build_growth([], TODAY)
    assert all(_row(r) == (D(0),) * 5 for r in empty["periods"] + empty["months"])
    single = g.build_growth([_pt(TODAY, 100, 130)], TODAY)
    p = {x["key"]: x for x in single["periods"]}
    assert _row(p["1y"]) == (D(0), D(130), D(100), D(30), D(130))
    assert p["1y"]["growth_pct"] is None
    assert _row(single["months"][-1]) == (D(0), D(130), D(100), D(30), D(130))
    assert _row(single["months"][0]) == (D(0),) * 5


def test_weekend_gaps_use_previous_point():
    # 31 Oct 2026 is a Saturday; 30 Sep a Wednesday. Only weekday points exist.
    pts = [
        _pt(date(2026, 9, 30), 1000, 1100),
        _pt(date(2026, 10, 30), 1200, 1500),  # Friday
        _pt(date(2026, 11, 2), 1200, 1550),  # Monday
        _pt(date(2026, 11, 3), 1200, 1560),
    ]
    p = {x["key"]: x for x in g.build_growth(pts, TODAY)["periods"]}
    # this_month start = 31 Oct -> Fri 30 Oct point 1500/1200
    assert _row(p["this_month"]) == (D(1500), D(1560), D(0), D(60), D(60))
    assert _row(p["last_month"]) == (D(1100), D(1500), D(200), D(200), D(400))


def test_negative_growth():
    pts = [_pt(date(2026, 10, 31), 1000, 1000), _pt(TODAY, 1000, 900)]
    p = {x["key"]: x for x in g.build_growth(pts, TODAY)["periods"]}
    assert _row(p["this_month"]) == (D(1000), D(900), D(0), D(-100), D(-100))
    assert p["this_month"]["growth_pct"] == D("-10.00")


def test_withdrawal_gives_negative_new_money():
    pts = [_pt(date(2026, 10, 31), 1000, 1200), _pt(TODAY, 800, 1000)]
    p = {x["key"]: x for x in g.build_growth(pts, TODAY)["periods"]}
    # nm = 800-1000 = -200; change = -200; growth = 0
    assert _row(p["this_month"]) == (D(1200), D(1000), D(-200), D(0), D(-200))
    assert p["this_month"]["growth_pct"] == D("0.00")


def test_paise_values_keep_identities_and_telescoping():
    pts = [
        _pt(date(2026, 9, 30), "1000.37", "1100.91"),
        _pt(date(2026, 10, 31), "1200.55", "1500.02"),
        _pt(TODAY, "1250.10", "1590.49"),
    ]
    result = g.build_growth(pts, TODAY)
    for r in result["periods"] + result["months"]:
        assert r["change"] == r["new_money"] + r["growth"]
        assert r["change"] == r["end_value"] - r["start_value"]
    m = result["months"]
    # 2dp inputs: no rounding drift, months telescope exactly. Oct: change 399.11; Nov: 90.47
    assert m[-2]["change"] == D("399.11") and m[-1]["change"] == D("90.47")
    assert m[-2]["new_money"] == D("200.18") and m[-2]["growth"] == D("198.93")
    assert sum(x["change"] for x in m) == D("1590.49") - D(0)
    assert sum(x["new_money"] for x in m) == D("1250.10")
    p = {x["key"]: x for x in result["periods"]}
    # this_month growth = 90.47 - 49.55 = 40.92; /1500.02*100 = 2.7279 -> 2.73
    assert p["this_month"]["growth"] == D("40.92") and p["this_month"]["growth_pct"] == D("2.73")


def test_sub_cent_inputs_identities_after_rounding():
    pts = [_pt(date(2026, 10, 31), "100.004", "100.004"), _pt(TODAY, "110.006", "120.004")]
    for r in g.build_growth(pts, TODAY)["periods"]:
        assert r["change"] == r["new_money"] + r["growth"]

"""Growth maths (services/analytics_growth.py) and GET /api/analytics/growth. Every expected figure
is hand-worked; `today` is 2026-11-03 unless a test says otherwise."""

from datetime import date
from decimal import Decimal

from app.routers import analytics as analytics_router
from app.services import analytics_growth as g
from tests.test_scoping import client, users  # noqa: F401  (fixtures)

TODAY = date(2026, 11, 3)


def _pt(d, invested, current):
    return {"date": d, "invested": Decimal(invested), "current": Decimal(current)}


POINTS = [
    _pt(date(2025, 11, 3), 100, 100),
    _pt(date(2026, 3, 31), 200, 260),
    _pt(date(2026, 9, 30), 300, 400),
    _pt(date(2026, 10, 31), 350, 450),
    _pt(date(2026, 11, 3), 360, 480),
]


def _periods(today):
    return {key: (start, end) for key, _label, start, end in g.period_bounds(today)}


# --- Period dates ------------------------------------------------------------------------------


def test_period_start_and_end_dates():
    assert _periods(TODAY) == {
        "this_month": (date(2026, 10, 31), TODAY),
        "last_month": (date(2026, 9, 30), date(2026, 10, 31)),
        "fy": (date(2026, 3, 31), TODAY),
        "ytd": (date(2025, 12, 31), TODAY),
        "1y": (date(2025, 11, 3), TODAY),
    }
    assert [p[0] for p in g.period_bounds(TODAY)] == ["this_month", "last_month", "fy", "ytd", "1y"]
    assert [p[1] for p in g.period_bounds(TODAY)] == [
        "This month", "Last month", "FY to date", "This year", "1 year"
    ]  # fmt: skip


def test_fy_start_in_january_to_march_is_previous_calendar_year():
    assert g.fy_start(date(2027, 1, 15)) == date(2026, 3, 31)
    assert g.fy_start(date(2027, 3, 31)) == date(2026, 3, 31)
    assert g.fy_start(date(2026, 4, 1)) == date(2026, 3, 31)
    assert g.fy_start(date(2026, 12, 31)) == date(2026, 3, 31)


def test_month_end_edges():
    # Leap year: month before 1 Mar 2028 ends on 29 Feb; before 1 Mar 2027 on 28 Feb.
    assert _periods(date(2028, 3, 10))["this_month"][0] == date(2028, 2, 29)
    assert _periods(date(2027, 3, 10))["this_month"][0] == date(2027, 2, 28)
    # Today the 31st of a month after a 30-day month; and January wraps into the prior year.
    assert _periods(date(2026, 5, 31))["last_month"] == (date(2026, 3, 31), date(2026, 4, 30))
    assert _periods(date(2027, 1, 31))["last_month"] == (date(2026, 11, 30), date(2026, 12, 31))
    assert _periods(date(2027, 1, 31))["this_month"][0] == date(2026, 12, 31)
    # 1 year back from 29 Feb lands on 28 Feb.
    assert _periods(date(2028, 2, 29))["1y"][0] == date(2027, 2, 28)


# --- Lookup ------------------------------------------------------------------------------------


def test_lookup_uses_point_on_or_before_date():
    lookup = g._Lookup(POINTS)
    assert lookup.at(date(2026, 3, 31)) == (Decimal(260), Decimal(200))  # exact
    assert lookup.at(date(2026, 4, 15)) == (Decimal(260), Decimal(200))  # before next point
    assert lookup.at(date(2030, 1, 1)) == (Decimal(480), Decimal(360))  # after the last
    assert lookup.at(date(2025, 11, 2)) == (Decimal(0), Decimal(0))  # before the first


def test_lookup_sorts_unordered_points():
    lookup = g._Lookup(list(reversed(POINTS)))
    assert lookup.at(date(2026, 10, 1)) == (Decimal(400), Decimal(300))


# --- Periods -----------------------------------------------------------------------------------


def _by_key(result):
    return {p["key"]: p for p in result["periods"]}


def test_period_figures():
    result = g.build_growth(POINTS, TODAY, date(2026, 1, 1))
    assert result["as_of"] == TODAY
    assert result["stocks_at_cost_before"] == date(2026, 1, 1)
    p = _by_key(result)

    def row(key):
        x = p[key]
        return tuple(
            x[k] for k in ("start_value", "end_value", "new_money", "growth", "change", "growth_pct")
        )

    D = Decimal
    assert row("this_month") == (D(450), D(480), D(10), D(20), D(30), D("4.44"))
    assert row("last_month") == (D(400), D(450), D(50), D(0), D(50), D("0.00"))
    assert row("fy") == (D(260), D(480), D(160), D(60), D(220), D("23.08"))
    # No point on or before 31 Dec 2025 except the first (3 Nov 2025): start from that.
    assert row("ytd") == (D(100), D(480), D(260), D(120), D(380), D("120.00"))
    assert row("1y") == (D(100), D(480), D(260), D(120), D(380), D("120.00"))
    assert p["last_month"]["start_date"] == date(2026, 9, 30)
    assert p["last_month"]["end_date"] == date(2026, 10, 31)


def test_change_equals_new_money_plus_growth():
    result = g.build_growth(POINTS, TODAY)
    for row in result["periods"] + result["months"]:
        assert row["change"] == row["new_money"] + row["growth"]


def test_identity_holds_after_rounding():
    points = [_pt(date(2026, 10, 31), "100.005", "100.005"), _pt(TODAY, "110.004", "120.006")]
    for row in g.build_growth(points, TODAY)["periods"]:
        assert row["change"] == row["new_money"] + row["growth"]


def test_zero_start_when_no_point_on_or_before_start():
    points = [_pt(date(2026, 10, 20), 500, 520), _pt(TODAY, 600, 650)]
    p = _by_key(g.build_growth(points, TODAY))
    # 31 Oct 2026 has a point (20 Oct); 30 Sep does not, so last month starts from zero.
    assert (p["last_month"]["start_value"], p["last_month"]["end_value"]) == (0, Decimal(520))
    assert p["last_month"]["new_money"] == 500
    assert p["last_month"]["growth"] == 20
    assert p["fy"]["start_value"] == 0
    assert p["fy"]["new_money"] == 600
    assert p["fy"]["growth"] == 50


def test_growth_pct_is_null_when_start_value_is_zero():
    points = [_pt(date(2026, 10, 20), 500, 520), _pt(TODAY, 600, 650)]
    p = _by_key(g.build_growth(points, TODAY))
    assert p["last_month"]["growth_pct"] is None
    assert p["1y"]["growth_pct"] is None
    # This month starts from 520: change 130, new money 100, growth 30, 30 / 520 = 5.77%.
    assert p["this_month"]["growth_pct"] == Decimal("5.77")


def test_no_points_gives_zero_rows():
    result = g.build_growth([], TODAY)
    assert result["stocks_at_cost_before"] is None
    assert all(p["growth_pct"] is None and p["change"] == 0 for p in result["periods"])
    assert len(result["months"]) == 12
    assert all(m["start_value"] == 0 and m["end_value"] == 0 for m in result["months"])


# --- Months ------------------------------------------------------------------------------------


def test_months_list_length_order_and_last_row():
    months = g.build_growth(POINTS, TODAY)["months"]
    assert len(months) == 12
    assert [m["month"] for m in months] == [
        "2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05",
        "2026-06", "2026-07", "2026-08", "2026-09", "2026-10", "2026-11",
    ]  # fmt: skip
    D = Decimal
    by_month = {m["month"]: m for m in months}
    nov = by_month["2026-11"]
    assert (nov["start_value"], nov["end_value"], nov["new_money"], nov["growth"]) == (
        D(450), D(480), D(10), D(20)
    )
    # October: 30 Sep (400/300) to 31 Oct (450/350).
    octo = by_month["2026-10"]
    assert (octo["start_value"], octo["end_value"], octo["new_money"], octo["growth"]) == (
        D(400), D(450), D(50), D(0)
    )
    # March: 28 Feb -> point of 3 Nov 2025 (100/100); 31 Mar (260/200).
    mar = by_month["2026-03"]
    assert (mar["start_value"], mar["end_value"], mar["new_money"], mar["growth"]) == (
        D(100), D(260), D(100), D(60)
    )


def test_months_across_year_boundary_in_january():
    months = g.build_growth(POINTS, date(2027, 1, 20))["months"]
    assert months[0]["month"] == "2026-02" and months[-1]["month"] == "2027-01"


# --- Endpoint ----------------------------------------------------------------------------------


class _FixedDate(date):
    @classmethod
    def today(cls):
        return TODAY


def test_requires_bearer(client):  # noqa: F811
    assert client.get("/api/analytics/growth").status_code == 401


def test_growth_endpoint_serialises_history(client, users, monkeypatch):  # noqa: F811
    seen = {}

    def fake_history(db, user_id, range_key, today=None):
        seen.update(user_id=user_id, range_key=range_key, today=today)
        return {"range": range_key, "points": POINTS, "stocks_at_cost_before": "2026-01-01"}

    monkeypatch.setattr(analytics_router, "date", _FixedDate)
    monkeypatch.setattr(analytics_router, "load_history", fake_history)
    response = client.get("/api/analytics/growth", headers=users[0])
    assert response.status_code == 200, response.text
    assert seen == {"user_id": users[1], "range_key": "1y", "today": TODAY}
    body = response.json()
    assert body["as_of"] == "2026-11-03"
    assert body["stocks_at_cost_before"] == "2026-01-01"
    assert [p["key"] for p in body["periods"]] == ["this_month", "last_month", "fy", "ytd", "1y"]
    fy = body["periods"][2]
    assert fy == {
        "key": "fy", "label": "FY to date", "start_date": "2026-03-31", "end_date": "2026-11-03",
        "start_value": 260, "end_value": 480, "new_money": 160, "growth": 60, "change": 220,
        "growth_pct": 23.08,
    }  # fmt: skip
    assert len(body["months"]) == 12 and body["months"][-1]["month"] == "2026-11"

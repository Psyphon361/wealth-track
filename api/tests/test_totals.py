from datetime import date
from decimal import Decimal

from app.routers import holdings
from app.routers.portfolio import build_dashboard, build_groups
from tests.conftest import make_fd, make_stock

TODAY = date(2026, 1, 1)


def _records():
    active = make_fd(start_date=date(2025, 7, 1))  # matures 2026-07-01
    matured = make_fd(start_date=date(2024, 1, 1))  # matured 2025-01-01
    stock = make_stock()  # 1000 invested
    return {"fd": [active, matured], "stock": [stock]}


def _group(groups, slug):
    return next(g for g in groups if g["type"] == slug)


def test_group_totals_exclude_matured():
    groups = build_groups(_records(), TODAY)
    fd = _group(groups, "fd")
    assert len(fd["items"]) == 2
    assert {i["status"] for i in fd["items"]} == {"active", "matured"}
    active = next(i for i in fd["items"] if i["status"] == "active")
    assert fd["count"] == 1
    assert fd["matured_count"] == 1
    assert fd["totals"]["invested"] == Decimal("100000.00")
    assert fd["totals"]["current_value"] == Decimal(str(active["current_value"]))
    assert fd["totals"]["gain"] == Decimal(str(active["gain"]))
    stock = _group(groups, "stock")
    assert stock["count"] == 1
    assert stock["matured_count"] == 0
    assert stock["totals"]["invested"] == Decimal("1000.00")


def test_dashboard_excludes_matured():
    groups = build_groups(_records(), TODAY)
    dash = build_dashboard(groups)
    fd = _group(groups, "fd")["totals"]
    stock = _group(groups, "stock")["totals"]
    assert dash["total_invested"] == fd["invested"] + stock["invested"]
    assert dash["total_current"] == fd["current_value"] + stock["current_value"]
    assert dash["total_gain"] == fd["gain"] + stock["gain"]
    by_type = {b["type"]: b for b in dash["by_type"]}
    assert by_type["fd"]["count"] == 1
    assert by_type["fd"]["matured_count"] == 1
    assert by_type["fd"]["invested"] == fd["invested"]
    assert by_type["fd"]["current"] == fd["current_value"]
    assert by_type["stock"]["count"] == 1
    expected = (fd["current_value"] / dash["total_current"] * 100).quantize(Decimal("0.01"))
    assert by_type["fd"]["allocation_pct"] == expected
    assert sum(b["allocation_pct"] for b in dash["by_type"]) == Decimal("100.00")


def test_holdings_summary_excludes_matured(monkeypatch):
    groups = build_groups(_records(), TODAY)
    fd_group = _group(groups, "fd")
    monkeypatch.setattr(holdings, "load_group", lambda db, slug, user_id: fd_group)
    out = holdings._run(
        None, 1, "fd", q=None, sort="current_value", dir="desc", page=1, multi={}
    )
    assert out["total"] == 2  # matured still listed
    summary = out["summary"]
    assert summary["count"] == 1
    assert summary["matured_count"] == 1
    assert summary["invested"] == fd_group["totals"]["invested"]
    assert summary["current_value"] == fd_group["totals"]["current_value"]
    assert summary["gain"] == fd_group["totals"]["gain"]
    assert summary["gain_pct"] == fd_group["totals"]["gain_pct"]

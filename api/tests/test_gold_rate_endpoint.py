from datetime import date, timedelta
from decimal import Decimal

from app.routers import master
from tests.test_scoping import client, users  # noqa: F401

MESSAGE = "Gold rate not available"
DESCRIPTION = "No IBJA rate on or just before this date. Enter the amount yourself."


def _rate_on(days_back):
    def fake(session, purity, on):
        return Decimal("7500.50"), on - timedelta(days=days_back)

    return fake


def test_rate_found_same_day(client, users, monkeypatch):  # noqa: F811
    monkeypatch.setattr(master.gold_rates, "rate_on_or_before", _rate_on(0))
    r = client.get("/api/master/gold/rate?purity=999&date=2026-10-01", headers=users[0])
    assert r.status_code == 200
    assert r.json() == {
        "purity": "999",
        "requested_date": "2026-10-01",
        "rate_date": "2026-10-01",
        "rate_per_gram": 7500.5,
    }


def test_rate_found_within_seven_days(client, users, monkeypatch):  # noqa: F811
    monkeypatch.setattr(master.gold_rates, "rate_on_or_before", _rate_on(7))
    r = client.get("/api/master/gold/rate?purity=916&date=2026-10-08", headers=users[0])
    assert r.status_code == 200
    assert r.json()["rate_date"] == "2026-10-01"


def test_rate_too_old_is_404(client, users, monkeypatch):  # noqa: F811
    monkeypatch.setattr(master.gold_rates, "rate_on_or_before", _rate_on(8))
    r = client.get("/api/master/gold/rate?purity=999&date=2026-10-09", headers=users[0])
    assert r.status_code == 404
    assert r.json()["message"] == MESSAGE
    assert r.json()["description"] == DESCRIPTION


def test_rate_missing_is_404(client, users, monkeypatch):  # noqa: F811
    monkeypatch.setattr(master.gold_rates, "rate_on_or_before", lambda s, p, o: None)
    r = client.get("/api/master/gold/rate?purity=999&date=2026-10-09", headers=users[0])
    assert r.status_code == 404
    assert r.json()["message"] == MESSAGE


def test_future_date_rejected(client, users):  # noqa: F811
    future = (date.today() + timedelta(days=1)).isoformat()
    r = client.get(f"/api/master/gold/rate?purity=999&date={future}", headers=users[0])
    assert r.status_code == 422


def test_bad_purity_rejected(client, users):  # noqa: F811
    r = client.get("/api/master/gold/rate?purity=800&date=2026-10-01", headers=users[0])
    assert r.status_code == 422
    assert "Choose a purity" in r.text

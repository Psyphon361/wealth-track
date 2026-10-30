from types import SimpleNamespace

import pytest

from app.routers import holdings
from tests.test_scoping import FD, STOCK, client, users  # noqa: F401

RD = {
    "bank": "Scoped Bank", "monthly_instalment": 5000, "rate": 7, "start_date": "2026-10-01",
    "compounding": "quarterly", "tenure_years": 1,
}  # fmt: skip
MF = {
    "scheme_name": "Scoped Fund", "category": "equity", "units": 10, "avg_nav": 100,
    "purchase_date": "2025-01-01",
}  # fmt: skip
PAYLOADS = {"fd": FD, "rd": RD, "stock": STOCK, "mf": MF}


@pytest.mark.parametrize("slug", sorted(PAYLOADS))
def test_detail_item_equals_list_row(client, users, slug):  # noqa: F811
    a, _, _, _ = users
    created = client.post(f"/api/assets/{slug}", json=PAYLOADS[slug], headers=a)
    assert created.status_code == 201
    item_id = created.json()["id"]
    row = client.get(f"/api/holdings/{slug}", headers=a).json()["items"][0]
    detail = client.get(f"/api/holdings/{slug}/{item_id}", headers=a)
    assert detail.status_code == 200
    body = detail.json()
    assert body["item"] == row
    assert body["master"] is None


def test_detail_not_found_message(client, users):  # noqa: F811
    a, _, b, _ = users
    item_id = client.post("/api/assets/fd", json=FD, headers=a).json()["id"]
    for headers, url in (
        (b, f"/api/holdings/fd/{item_id}"),
        (a, "/api/holdings/fd/999999"),
        (a, f"/api/holdings/nope/{item_id}"),
    ):
        response = client.get(url, headers=headers)
        assert response.status_code == 404
        assert response.json()["message"] == "Holding not found"
        assert response.json()["description"] == (
            "It may have been deleted, or it belongs to another account."
        )


def test_detail_requires_auth(client):  # noqa: F811
    assert client.get("/api/holdings/fd/1").status_code == 401


def test_linked_master_present_and_null(monkeypatch):
    stock = SimpleNamespace(
        id=7, isin="INE000A01010", kind="equity", name="Probe Ltd", nse_symbol="PRB",
        nse_series="EQ", bse_code=None, bse_symbol=None, bse_group=None, face_value=None,
        is_active=True,
    )  # fmt: skip
    monkeypatch.setattr(holdings.stock_master, "get_stock_master", lambda db, i: stock)
    linked = holdings.linked_master(None, "stock", SimpleNamespace(master_id=7))
    assert linked["id"] == 7 and linked["nse_symbol"] == "PRB"
    assert holdings.linked_master(None, "stock", SimpleNamespace(master_id=None)) is None
    assert holdings.linked_master(None, "fd", SimpleNamespace(issuer_id=None)) is None
    assert holdings.linked_master(None, "mf", SimpleNamespace(scheme_code=None)) is None
    monkeypatch.setattr(holdings.stock_master, "get_stock_master", lambda db, i: None)
    assert holdings.linked_master(None, "stock", SimpleNamespace(master_id=7)) is None

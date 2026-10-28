import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.main import app
from app.models import Bond, FixedDeposit, MFNavLatest, MutualFund, RecurringDeposit, Stock

PASSWORD = "a-long-password"
FD = {
    "bank": "Scoped Bank", "principal": 100000, "rate": 7, "start_date": "2026-10-01",
    "compounding": "quarterly", "payout_type": "cumulative", "tenure_years": 1,
}  # fmt: skip
STOCK = {
    "name": "Scoped Stock", "exchange": "NSE", "quantity": 10, "avg_buy_price": 100,
    "buy_date": "2025-01-01",
}  # fmt: skip


@pytest.fixture
def client(auth_engine, auth_settings):
    # Master tables need Postgres; only the holdings tables and the NAV table are created.
    Base.metadata.create_all(
        auth_engine,
        tables=[
            m.__table__
            for m in (FixedDeposit, RecurringDeposit, Stock, Bond, MutualFund, MFNavLatest)
        ],
    )
    factory = sessionmaker(bind=auth_engine, expire_on_commit=False)

    def override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def _signup(client, email):
    body = client.post("/api/auth/signup", json={"email": email, "password": PASSWORD}).json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]["id"]


@pytest.fixture
def users(client, auth_settings):
    auth_settings.allowed_emails = ["a@example.com", "b@example.com"]
    a, a_id = _signup(client, "a@example.com")
    b, b_id = _signup(client, "b@example.com")
    return a, a_id, b, b_id


def test_lists_are_scoped(client, users):
    a, _, b, _ = users
    assert client.post("/api/assets/fd", json=FD, headers=a).status_code == 201
    assert client.post("/api/assets/stock", json=STOCK, headers=a).status_code == 201
    assert len(client.get("/api/assets/fd", headers=a).json()) == 1
    assert client.get("/api/assets/fd", headers=b).json() == []
    assert client.get("/api/assets/stock", headers=b).json() == []


def test_portfolio_dashboard_holdings_are_scoped(client, users):
    a, _, b, _ = users
    client.post("/api/assets/fd", json=FD, headers=a)
    mine = client.get("/api/portfolio", headers=a).json()["groups"]
    assert sum(len(g["items"]) for g in mine) == 1
    theirs = client.get("/api/portfolio", headers=b).json()["groups"]
    assert all(g["items"] == [] for g in theirs)
    dash_a = client.get("/api/dashboard", headers=a).json()
    dash_b = client.get("/api/dashboard", headers=b).json()
    assert float(dash_a["total_invested"]) == 100000
    assert float(dash_b["total_invested"]) == 0
    assert client.get("/api/holdings/fd", headers=a).json()["total"] == 1
    assert client.get("/api/holdings/fd", headers=b).json()["total"] == 0


def test_other_users_item_is_not_found(client, users):
    a, _, b, _ = users
    item_id = client.post("/api/assets/fd", json=FD, headers=a).json()["id"]
    url = f"/api/assets/fd/{item_id}"
    for response in (
        client.get(url, headers=b),
        client.put(url, json=FD, headers=b),
        client.delete(url, headers=b),
    ):
        assert response.status_code == 404
        assert response.json()["message"] == "Fixed deposit not found"
    assert client.get(url, headers=a).status_code == 200
    assert client.delete(url, headers=a).status_code == 200


def test_create_ignores_user_id_in_payload(client, users):
    a, a_id, b, b_id = users
    body = client.post("/api/assets/fd", json={**FD, "user_id": b_id}, headers=a).json()
    assert "user_id" not in body
    assert len(client.get("/api/assets/fd", headers=a).json()) == 1
    assert client.get("/api/assets/fd", headers=b).json() == []


@pytest.mark.parametrize(
    "path",
    ["/api/assets/fd", "/api/portfolio", "/api/dashboard", "/api/holdings/fd", "/api/master/mf"],
)
def test_requires_bearer(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer nonsense"}).status_code == 401

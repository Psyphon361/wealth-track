import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.db import get_db
from app.main import app
from app.models.user import User
from app.services import auth

PASSWORD = "a-long-password"


@pytest.fixture
def client(auth_engine, auth_settings):
    factory = sessionmaker(bind=auth_engine, expire_on_commit=False)

    def override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def signup(client, email="invited@example.com", password=PASSWORD):
    return client.post("/api/auth/signup", json={"email": email, "password": password})


def test_signup_returns_tokens_and_me_works(client):
    response = signup(client, "Invited@Example.com ")
    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "invited@example.com"
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json() == body["user"]


def test_signup_not_invited(client):
    response = signup(client, "stranger@example.com")
    assert response.status_code == 403
    assert response.json()["message"] == "Sign-ups are invite-only"
    assert response.json()["description"] == "This email isn't on the invite list."


def test_signup_duplicate(client):
    assert signup(client).status_code == 201
    response = signup(client)
    assert response.status_code == 409
    assert response.json()["message"] == "An account with this email already exists"
    assert response.json()["description"] == "Log in instead."


def test_signup_existing_user_without_password_is_conflict(client, auth_engine):
    with sessionmaker(bind=auth_engine)() as session:
        session.add(User(email="invited@example.com"))
        session.commit()
    assert signup(client).status_code == 409


def test_signup_validation_messages(client):
    response = signup(client, "not-an-email", "short")
    assert response.status_code == 422
    body = response.json()
    assert body["message"] == "Check the highlighted fields"
    messages = {tuple(e["loc"])[-1]: e["msg"] for e in body["detail"]}
    assert messages["email"] == "Enter a valid email address"
    assert signup(client, "invited@example.com", "short").json()["detail"][0]["msg"] == (
        "Password must be at least 10 characters"
    )
    assert signup(client, "invited@example.com", "x" * 129).json()["detail"][0]["msg"] == (
        "Password must be at most 128 characters"
    )


def test_login_validation_requires_password(client):
    response = client.post("/api/auth/login", json={"email": "a@example.com", "password": ""})
    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == "Required"
    assert client.post("/api/auth/login", json={"email": "a@example.com"}).json()["detail"][0]["msg"] == "Required"


def test_login_success_and_wrong_credentials(client):
    signup(client)
    ok = client.post("/api/auth/login", json={"email": "INVITED@example.com", "password": PASSWORD})
    assert ok.status_code == 200
    assert ok.json()["access_token"]
    for payload in (
        {"email": "invited@example.com", "password": "wrong-password"},
        {"email": "ghost@example.com", "password": PASSWORD},
    ):
        bad = client.post("/api/auth/login", json=payload)
        assert bad.status_code == 401
        assert bad.json()["message"] == "Incorrect email or password"
        assert bad.json()["description"] == "Check your details and try again."


def test_login_inactive_user_rejected(client, auth_engine):
    signup(client)
    with sessionmaker(bind=auth_engine)() as session:
        user = auth.get_user_by_email(session, "invited@example.com")
        user.is_active = False
        session.commit()
    response = client.post("/api/auth/login", json={"email": "invited@example.com", "password": PASSWORD})
    assert response.status_code == 401


def test_login_rate_limited_after_five_failures(client):
    signup(client)
    payload = {"email": "invited@example.com", "password": "wrong-password"}
    for _ in range(5):
        assert client.post("/api/auth/login", json=payload).status_code == 401
    blocked = client.post("/api/auth/login", json={**payload, "password": PASSWORD})
    assert blocked.status_code == 429
    assert blocked.json()["message"] == "Too many attempts"
    assert blocked.json()["description"] == "Wait 15 minutes and try again."
    unknown = {"email": "ghost@example.com", "password": "x"}
    for _ in range(5):
        client.post("/api/auth/login", json=unknown)
    assert client.post("/api/auth/login", json=unknown).status_code == 429


def test_refresh_rotates_and_logout_revokes(client):
    tokens = signup(client).json()
    refreshed = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    new_refresh = refreshed.json()["refresh_token"]
    assert new_refresh != tokens["refresh_token"]
    out = client.post("/api/auth/logout", json={"refresh_token": new_refresh})
    assert out.status_code == 200
    assert out.json() == {"message": "Logged out", "description": "You have been logged out."}
    after = client.post("/api/auth/refresh", json={"refresh_token": new_refresh})
    assert after.status_code == 401
    assert after.json()["message"] == "Not authorised"
    assert after.json()["description"] == "Your session may have expired. Log in again."


def test_me_requires_valid_bearer(client):
    for headers in ({}, {"Authorization": "Bearer junk"}, {"Authorization": "Basic abc"}):
        response = client.get("/api/auth/me", headers=headers)
        assert response.status_code == 401
        assert response.json()["message"] == "Not authorised"

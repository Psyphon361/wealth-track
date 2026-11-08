import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db import get_db
from app.main import app
from app.models.user import User
from app.services import google_auth

PASSWORD = "a-long-password"
EMAIL = "invited@example.com"
CLIENT_ID = "test-client-id.apps.googleusercontent.com"
VERIFIER = "v" * 64
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def client(auth_engine, auth_settings, monkeypatch):
    monkeypatch.setattr(auth_settings, "google_client_id", CLIENT_ID)
    monkeypatch.setattr(auth_settings, "google_client_secret", "secret")
    monkeypatch.setattr(google_auth, "_signing_key", lambda token: KEY.public_key())
    factory = sessionmaker(bind=auth_engine, expire_on_commit=False)

    def override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def signup(client, **extra):
    return client.post(
        "/api/auth/signup", json={"email": EMAIL, "password": PASSWORD, **extra}
    )


def auth_header(body):
    return {"Authorization": f"Bearer {body['access_token']}"}


def google(client, monkeypatch, **claims):
    now = int(time.time())
    base = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "google-sub-1",
        "email": EMAIL,
        "email_verified": True,
        "iat": now,
        "exp": now + 3600,
    }
    base.update(claims)
    token = jwt.encode(base, KEY, algorithm="RS256", headers={"kid": "k1"})
    monkeypatch.setattr(google_auth, "exchange_code", lambda c, v, u: token)
    return client.post(
        "/api/auth/google",
        json={"code": "abc", "code_verifier": VERIFIER, "redirect_uri": "http://localhost:3000/cb"},
    )


def stored_name(auth_engine):
    with sessionmaker(bind=auth_engine)() as session:
        return session.scalar(select(User)).full_name


def test_signup_without_name(client):
    body = signup(client).json()
    assert body["user"]["full_name"] is None
    me = client.get("/api/auth/me", headers=auth_header(body))
    assert me.json()["full_name"] is None


def test_signup_with_name_trims_and_collapses(client):
    body = signup(client, full_name="  Asha   K  Rao ").json()
    assert body["user"]["full_name"] == "Asha K Rao"
    me = client.get("/api/auth/me", headers=auth_header(body))
    assert me.json()["full_name"] == "Asha K Rao"


def test_signup_blank_name_is_null(client):
    assert signup(client, full_name="   ").json()["user"]["full_name"] is None


def test_signup_name_too_long(client):
    response = signup(client, full_name="x" * 81)
    assert response.status_code == 422
    error = response.json()["detail"][0]
    assert error["loc"][-1] == "full_name"
    assert error["msg"] == "Name is too long (80 characters at most)"


def test_patch_sets_trims_and_collapses(client, auth_engine):
    body = signup(client).json()
    response = client.patch(
        "/api/auth/me", json={"full_name": "  Asha \t Rao  "}, headers=auth_header(body)
    )
    assert response.status_code == 200
    out = response.json()
    assert out["message"] == "Name updated"
    assert out["description"] == "Asha Rao"
    assert out["user"]["full_name"] == "Asha Rao"
    assert stored_name(auth_engine) == "Asha Rao"
    me = client.get("/api/auth/me", headers=auth_header(body))
    assert me.json()["full_name"] == "Asha Rao"


def test_patch_accepts_80_characters(client):
    body = signup(client).json()
    response = client.patch("/api/auth/me", json={"full_name": "x" * 80}, headers=auth_header(body))
    assert response.status_code == 200


def test_patch_blank_name(client, auth_engine):
    body = signup(client, full_name="Asha").json()
    response = client.patch("/api/auth/me", json={"full_name": "   "}, headers=auth_header(body))
    assert response.status_code == 422
    error = response.json()["detail"][0]
    assert error["loc"][-1] == "full_name"
    assert error["msg"] == "Enter your name"
    assert stored_name(auth_engine) == "Asha"


def test_patch_name_too_long(client):
    body = signup(client).json()
    response = client.patch("/api/auth/me", json={"full_name": "x" * 81}, headers=auth_header(body))
    assert response.status_code == 422
    error = response.json()["detail"][0]
    assert error["loc"][-1] == "full_name"
    assert error["msg"] == "Name is too long (80 characters at most)"


def test_patch_requires_auth(client):
    assert client.patch("/api/auth/me", json={"full_name": "Asha"}).status_code == 401


def test_google_creates_user_with_name(client, auth_engine, monkeypatch):
    response = google(client, monkeypatch, name="  Asha   Rao ")
    assert response.status_code == 200
    assert response.json()["user"]["full_name"] == "Asha Rao"
    assert stored_name(auth_engine) == "Asha Rao"


def test_google_fills_empty_name_on_link(client, auth_engine, monkeypatch):
    assert signup(client).status_code == 201
    response = google(client, monkeypatch, name="Asha Rao")
    assert response.json()["user"]["full_name"] == "Asha Rao"
    assert stored_name(auth_engine) == "Asha Rao"


def test_google_does_not_overwrite_name(client, auth_engine, monkeypatch):
    assert signup(client, full_name="My Name").status_code == 201
    response = google(client, monkeypatch, name="Google Name")
    assert response.json()["user"]["full_name"] == "My Name"
    assert stored_name(auth_engine) == "My Name"


def test_google_without_name_claim_leaves_null(client, auth_engine, monkeypatch):
    response = google(client, monkeypatch)
    assert response.json()["user"]["full_name"] is None
    assert stored_name(auth_engine) is None


def test_google_long_name_is_cut(client, auth_engine, monkeypatch):
    google(client, monkeypatch, name="y" * 120)
    assert stored_name(auth_engine) == "y" * 80

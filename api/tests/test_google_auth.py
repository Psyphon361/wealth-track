import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db import get_db
from app.main import app
from app.models.login_attempt import LoginAttempt
from app.models.user import User
from app.services import google_auth

CLIENT_ID = "test-client-id.apps.googleusercontent.com"
EMAIL = "invited@example.com"
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


def make_token(monkeypatch, **overrides):
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "google-sub-1",
        "email": EMAIL,
        "email_verified": True,
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(overrides)
    token = jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": "k1"})
    monkeypatch.setattr(google_auth, "exchange_code", lambda code, verifier, uri: token)


def post(client):
    return client.post(
        "/api/auth/google",
        json={"code": "abc", "code_verifier": VERIFIER, "redirect_uri": "http://localhost:3000/cb"},
    )


def users(auth_engine):
    with sessionmaker(bind=auth_engine)() as session:
        return list(session.scalars(select(User)))


def test_new_allowlisted_user_created(client, auth_engine, monkeypatch):
    make_token(monkeypatch)
    response = post(client)
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == EMAIL
    assert body["access_token"] and body["refresh_token"]
    [user] = users(auth_engine)
    assert user.password_hash is None
    assert user.google_sub == "google-sub-1"
    assert user.last_login_at is not None
    with sessionmaker(bind=auth_engine)() as session:
        assert session.scalar(select(LoginAttempt)) is None


def test_same_sub_signs_in_again(client, auth_engine, monkeypatch):
    make_token(monkeypatch)
    first = post(client).json()["user"]["id"]
    assert post(client).json()["user"]["id"] == first
    assert len(users(auth_engine)) == 1


def test_existing_password_user_is_linked(client, auth_engine, monkeypatch):
    signup = client.post("/api/auth/signup", json={"email": EMAIL, "password": "a-long-password"})
    assert signup.status_code == 201
    make_token(monkeypatch)
    response = post(client)
    assert response.status_code == 200
    assert response.json()["user"]["id"] == signup.json()["user"]["id"]
    assert users(auth_engine)[0].google_sub == "google-sub-1"
    login = client.post("/api/auth/login", json={"email": EMAIL, "password": "a-long-password"})
    assert login.status_code == 200
    assert post(client).status_code == 200


def test_unverified_email(client, monkeypatch):
    make_token(monkeypatch, email_verified=False)
    response = post(client)
    assert response.status_code == 403
    assert response.json()["message"] == "Google email not verified"
    assert response.json()["description"] == "Verify your email with Google, then try again."


def test_not_allowlisted(client, auth_engine, monkeypatch):
    make_token(monkeypatch, email="stranger@example.com")
    response = post(client)
    assert response.status_code == 403
    assert response.json()["message"] == "Sign-ups are invite-only"
    assert response.json()["description"] == "This email isn't on the invite list."
    assert users(auth_engine) == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "someone-else"},
        {"iss": "https://evil.example.com"},
        {"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200},
    ],
)
def test_bad_token_claims(client, monkeypatch, overrides):
    make_token(monkeypatch, **overrides)
    response = post(client)
    assert response.status_code == 401
    assert response.json()["message"] == "Google sign-in failed"
    assert response.json()["description"] == "Try again, or log in with your email."


def test_alternate_issuer_accepted(client, monkeypatch):
    make_token(monkeypatch, iss="accounts.google.com")
    assert post(client).status_code == 200


def test_exchange_failure(client, monkeypatch):
    def boom(code, verifier, uri):
        raise google_auth.GoogleAuthError("nope")

    monkeypatch.setattr(google_auth, "exchange_code", boom)
    assert post(client).status_code == 401


def test_unconfigured(client, auth_settings, monkeypatch):
    monkeypatch.setattr(auth_settings, "google_client_id", None)
    response = post(client)
    assert response.status_code == 503
    assert response.json()["message"] == "Google sign-in isn't configured"
    assert response.json()["description"] == "Use your email and password for now."


def test_inactive_user(client, auth_engine, monkeypatch):
    with sessionmaker(bind=auth_engine)() as session:
        session.add(User(email=EMAIL, is_active=False))
        session.commit()
    make_token(monkeypatch)
    response = post(client)
    assert response.status_code == 401
    assert response.json()["message"] == "Incorrect email or password"


def test_request_validation(client):
    bad = client.post(
        "/api/auth/google", json={"code": "abc", "code_verifier": "short", "redirect_uri": "ftp://x"}
    )
    assert bad.status_code == 422

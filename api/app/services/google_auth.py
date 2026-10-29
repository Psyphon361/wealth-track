"""Sign in with Google: authorization-code exchange, ID token verification, user lookup/linking."""

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.user import User
from app.services.auth import normalise_email

TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")
TIMEOUT = 10

_jwk_client = jwt.PyJWKClient(JWKS_URL)


class GoogleAuthError(Exception):
    """Code exchange or ID token verification failed."""


class GoogleEmailNotVerified(Exception):
    """Google reports the email as unverified."""


class NotAllowlisted(Exception):
    """No account exists and the email is not on the invite list."""


class InactiveUser(Exception):
    """The matching account is deactivated."""


def _post_token(data: dict[str, str]) -> dict:
    """POST the token request; module-level so tests can replace it."""
    request = urllib.request.Request(
        TOKEN_URL,
        data=urllib.parse.urlencode(data).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
        return json.loads(response.read())


def _signing_key(id_token: str):
    """Public key for the token's kid; module-level so tests can replace it."""
    return _jwk_client.get_signing_key_from_jwt(id_token).key


def exchange_code(code: str, code_verifier: str, redirect_uri: str) -> str:
    data = {
        "code": code,
        "client_id": settings.google_client_id or "",
        "client_secret": settings.google_client_secret or "",
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": code_verifier,
    }
    try:
        body = _post_token(data)
        id_token = body["id_token"]
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as exc:
        raise GoogleAuthError("code exchange failed") from exc
    if not isinstance(id_token, str) or not id_token:
        raise GoogleAuthError("no id_token")
    return id_token


def verify_id_token(id_token: str) -> dict:
    try:
        key = _signing_key(id_token)
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=settings.google_client_id,
            leeway=30,
            options={"require": ["exp", "iat", "sub", "email"], "verify_iss": False},
        )
    except (jwt.PyJWTError, OSError, ValueError) as exc:
        raise GoogleAuthError("invalid id_token") from exc
    if claims.get("iss") not in ISSUERS:
        raise GoogleAuthError("bad issuer")
    return claims


def _verified(claims: dict) -> bool:
    return claims.get("email_verified") in (True, "true")


def sign_in_with_google(session: Session, claims: dict, allowed_emails: list[str]) -> User:
    if not _verified(claims):
        raise GoogleEmailNotVerified
    email = normalise_email(claims["email"])
    sub = str(claims["sub"])
    user = session.scalar(select(User).where(User.google_sub == sub))
    if user is None:
        user = session.scalar(select(User).where(User.email == email))
        if user is not None:
            if user.google_sub and user.google_sub != sub:
                raise GoogleAuthError("account linked to another Google identity")
            user.google_sub = sub
        elif email in allowed_emails:
            user = User(email=email, google_sub=sub, is_active=True)
            session.add(user)
        else:
            raise NotAllowlisted
    if not user.is_active:
        raise InactiveUser
    user.last_login_at = datetime.now(UTC)
    session.commit()
    return user

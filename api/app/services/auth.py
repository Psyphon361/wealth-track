"""Authentication core: password hashing, JWT access tokens, rotating refresh tokens, rate limit."""

import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models.login_attempt import LoginAttempt
from app.models.refresh_token import RefreshToken
from app.models.user import User

ACCESS_TTL = timedelta(minutes=15)
REFRESH_TTL = timedelta(days=30)
REFRESH_REUSE_GRACE = timedelta(seconds=60)
RATE_LIMIT_FAILURES = 5
RATE_LIMIT_WINDOW = timedelta(minutes=15)

PASSWORD_MIN = 10
PASSWORD_MAX = 128
EMAIL_MAX = 320

JWT_ALGORITHM = "HS256"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")

_hasher = PasswordHasher()  # argon2id defaults
# Verified against when the email is unknown so response time doesn't reveal existence.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


class AuthConfigError(RuntimeError):
    """JWT_SECRET is not configured."""


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    """SQLite drops tzinfo; treat stored naive datetimes as UTC."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


# --- validation -----------------------------------------------------------------------------


def normalise_email(email: str) -> str:
    return email.strip().lower()


def is_valid_email(email: str) -> bool:
    return len(email) <= EMAIL_MAX and bool(_EMAIL_RE.match(email))


def password_error(password: str) -> str | None:
    if len(password) < PASSWORD_MIN:
        return f"Password must be at least {PASSWORD_MIN} characters"
    if len(password) > PASSWORD_MAX:
        return f"Password must be at most {PASSWORD_MAX} characters"
    return None


# --- passwords ------------------------------------------------------------------------------


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Verify against the stored hash; a missing hash is checked against a dummy (constant work)."""
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def verify_unknown_user(password: str) -> None:
    """Spend the same time as a real verification when the email doesn't exist."""
    verify_password(None, password)


# --- access tokens --------------------------------------------------------------------------


def _secret() -> str:
    if not settings.jwt_secret:
        raise AuthConfigError("JWT_SECRET is not set")
    return settings.jwt_secret


def create_access_token(user: User, now: datetime | None = None) -> tuple[str, datetime]:
    issued = now or _now()
    expires = issued + ACCESS_TTL
    claims = {
        "sub": str(user.id),
        "email": user.email,
        "typ": "access",
        "iat": int(issued.timestamp()),
        "exp": int(expires.timestamp()),
    }
    return jwt.encode(claims, _secret(), algorithm=JWT_ALGORITHM), expires


def decode_access_token(token: str) -> dict | None:
    """Return the claims, or None if the token is invalid, expired or not an access token."""
    try:
        claims = jwt.decode(
            token,
            _secret(),
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "exp", "iat", "typ"]},
        )
    except jwt.PyJWTError:
        return None
    if claims.get("typ") != "access":
        return None
    return claims


# --- refresh tokens -------------------------------------------------------------------------


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token_pair(
    session: Session, user: User, family_id: str | None = None, now: datetime | None = None
) -> TokenPair:
    issued = now or _now()
    access, access_expires = create_access_token(user, issued)
    refresh = secrets.token_urlsafe(32)
    refresh_expires = issued + REFRESH_TTL
    session.add(
        RefreshToken(
            user_id=user.id,
            family_id=family_id or str(uuid.uuid4()),
            token_hash=_hash_token(refresh),
            expires_at=refresh_expires,
        )
    )
    session.commit()
    return TokenPair(access, access_expires, refresh, refresh_expires)


def _revoke_family_id(session: Session, family_id: str, now: datetime) -> None:
    session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    session.commit()


def rotate_refresh(
    session: Session, token: str, now: datetime | None = None
) -> tuple[User, TokenPair] | None:
    """Exchange a refresh token for a new pair; None means the token is invalid."""
    moment = now or _now()
    row = session.scalar(select(RefreshToken).where(RefreshToken.token_hash == _hash_token(token)))
    if row is None or row.revoked_at is not None or _aware(row.expires_at) <= moment:
        return None
    user = session.get(User, row.user_id)
    if user is None or not user.is_active:
        return None
    if row.replaced_at is not None:
        if moment - _aware(row.replaced_at) > REFRESH_REUSE_GRACE:
            # A rotated token came back after the grace window: assume theft, kill the family.
            _revoke_family_id(session, row.family_id, moment)
            return None
        return user, issue_token_pair(session, user, row.family_id, moment)
    row.replaced_at = moment
    return user, issue_token_pair(session, user, row.family_id, moment)


def revoke_family(session: Session, token: str, now: datetime | None = None) -> bool:
    """Revoke every token in the token's family (logout). False if the token is unknown."""
    row = session.scalar(select(RefreshToken).where(RefreshToken.token_hash == _hash_token(token)))
    if row is None:
        return False
    _revoke_family_id(session, row.family_id, now or _now())
    return True


# --- rate limiting --------------------------------------------------------------------------


def is_rate_limited(session: Session, email: str, now: datetime | None = None) -> bool:
    since = (now or _now()) - RATE_LIMIT_WINDOW
    failures = session.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(
            LoginAttempt.email == email,
            LoginAttempt.attempted_at >= since,
            LoginAttempt.succeeded.is_(False),
        )
    )
    return (failures or 0) >= RATE_LIMIT_FAILURES


def record_attempt(
    session: Session, email: str, succeeded: bool, now: datetime | None = None
) -> None:
    session.add(LoginAttempt(email=email, attempted_at=now or _now(), succeeded=succeeded))
    session.commit()


# --- users ----------------------------------------------------------------------------------


def get_user_by_email(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(User.email == email))

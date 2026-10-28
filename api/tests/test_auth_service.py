from datetime import UTC, datetime, timedelta

import jwt

from app.config import Settings
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services import auth


def make_user(session, email="a@example.com"):
    user = User(email=email, password_hash=auth.hash_password("correct horse"))
    session.add(user)
    session.commit()
    return user


def test_password_hash_and_verify():
    hashed = auth.hash_password("correct horse")
    assert hashed.startswith("$argon2id$")
    assert auth.verify_password(hashed, "correct horse")
    assert not auth.verify_password(hashed, "wrong")
    assert not auth.needs_rehash(hashed)


def test_verify_without_hash_is_false():
    assert not auth.verify_password(None, "anything")


def test_access_token_round_trip(db_session):
    user = make_user(db_session)
    token, expires = auth.create_access_token(user)
    claims = auth.decode_access_token(token)
    assert claims["sub"] == str(user.id)
    assert claims["email"] == user.email
    assert claims["typ"] == "access"
    assert claims["exp"] - claims["iat"] == int(auth.ACCESS_TTL.total_seconds())
    assert int(expires.timestamp()) == claims["exp"]


def test_expired_access_token_rejected(db_session):
    user = make_user(db_session)
    token, _ = auth.create_access_token(user, datetime.now(UTC) - timedelta(hours=1))
    assert auth.decode_access_token(token) is None


def test_wrong_typ_and_bad_signature_rejected(db_session, auth_settings):
    now = int(datetime.now(UTC).timestamp())
    claims = {"sub": "1", "email": "a@example.com", "typ": "refresh", "iat": now, "exp": now + 60}
    wrong_typ = jwt.encode(claims, auth_settings.jwt_secret, algorithm="HS256")
    assert auth.decode_access_token(wrong_typ) is None
    forged = jwt.encode({**claims, "typ": "access"}, "another-secret-another-secret-12345", algorithm="HS256")
    assert auth.decode_access_token(forged) is None
    assert auth.decode_access_token("not-a-jwt") is None


def test_email_validation_and_normalisation():
    assert auth.normalise_email("  Foo@Example.COM ") == "foo@example.com"
    assert auth.is_valid_email("foo@example.com")
    assert auth.is_valid_email("a.b+c@mail.example.co.in")
    for bad in ("foo", "foo@", "@example.com", "foo@example", "foo bar@example.com", "a@b@c.com"):
        assert not auth.is_valid_email(bad), bad
    assert not auth.is_valid_email("a" * 320 + "@example.com")


def test_password_rules():
    assert auth.password_error("x" * 9) == "Password must be at least 10 characters"
    assert auth.password_error("x" * 10) is None
    assert auth.password_error("x" * 128) is None
    assert auth.password_error("x" * 129) == "Password must be at most 128 characters"


def test_allowed_emails_parsed_from_comma_string():
    parsed = Settings(allowed_emails=" A@x.com, b@Y.com ,,", _env_file=None)
    assert parsed.allowed_emails == ["a@x.com", "b@y.com"]


def test_refresh_rotation_marks_old_token_replaced(db_session):
    user = make_user(db_session)
    first = auth.issue_token_pair(db_session, user)
    _, second = auth.rotate_refresh(db_session, first.refresh_token)
    assert second.refresh_token != first.refresh_token
    old = db_session.query(RefreshToken).filter_by(token_hash=auth._hash_token(first.refresh_token)).one()
    assert old.replaced_at is not None and old.revoked_at is None
    assert auth.rotate_refresh(db_session, second.refresh_token) is not None


def test_refresh_reuse_within_grace_issues_new_pair_in_same_family(db_session):
    user = make_user(db_session)
    now = datetime.now(UTC)
    first = auth.issue_token_pair(db_session, user, now=now)
    auth.rotate_refresh(db_session, first.refresh_token, now=now)
    _, again = auth.rotate_refresh(db_session, first.refresh_token, now=now + timedelta(seconds=30))
    families = {row.family_id for row in db_session.query(RefreshToken).all()}
    assert len(families) == 1
    assert all(row.revoked_at is None for row in db_session.query(RefreshToken).all())
    assert auth.rotate_refresh(db_session, again.refresh_token, now=now + timedelta(seconds=31)) is not None


def test_refresh_reuse_after_grace_revokes_family(db_session):
    user = make_user(db_session)
    now = datetime.now(UTC)
    first = auth.issue_token_pair(db_session, user, now=now)
    _, second = auth.rotate_refresh(db_session, first.refresh_token, now=now)
    later = now + timedelta(seconds=120)
    assert auth.rotate_refresh(db_session, first.refresh_token, now=later) is None
    assert all(row.revoked_at is not None for row in db_session.query(RefreshToken).all())
    assert auth.rotate_refresh(db_session, second.refresh_token, now=later) is None


def test_refresh_unknown_expired_and_revoked_are_invalid(db_session):
    user = make_user(db_session)
    assert auth.rotate_refresh(db_session, "nope") is None
    now = datetime.now(UTC)
    pair = auth.issue_token_pair(db_session, user, now=now)
    assert auth.rotate_refresh(db_session, pair.refresh_token, now=now + auth.REFRESH_TTL + timedelta(seconds=1)) is None
    fresh = auth.issue_token_pair(db_session, user)
    assert auth.revoke_family(db_session, fresh.refresh_token)
    assert auth.rotate_refresh(db_session, fresh.refresh_token) is None


def test_rate_limit_counts_recent_failures_only(db_session):
    now = datetime.now(UTC)
    for _ in range(4):
        auth.record_attempt(db_session, "a@example.com", False, now=now)
    assert not auth.is_rate_limited(db_session, "a@example.com", now=now)
    auth.record_attempt(db_session, "a@example.com", False, now=now)
    assert auth.is_rate_limited(db_session, "a@example.com", now=now)
    assert not auth.is_rate_limited(db_session, "other@example.com", now=now)
    assert not auth.is_rate_limited(db_session, "a@example.com", now=now + timedelta(minutes=16))

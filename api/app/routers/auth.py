from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from pydantic_core import PydanticCustomError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import current_user
from app.models.user import User
from app.schemas.messages import Outcome
from app.services import auth, google_auth

router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_EMAIL = "Enter a valid email address"


def _email(value: str) -> str:
    email = auth.normalise_email(value)
    if not auth.is_valid_email(email):
        raise PydanticCustomError("invalid_email", INVALID_EMAIL)
    return email


class SignupIn(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def check_email(cls, value: str) -> str:
        return _email(value)

    @field_validator("password")
    @classmethod
    def check_password(cls, value: str) -> str:
        message = auth.password_error(value)
        if message:
            raise PydanticCustomError("invalid_password", message)
        return value


class LoginIn(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def check_email(cls, value: str) -> str:
        return _email(value)

    @field_validator("password")
    @classmethod
    def check_password(cls, value: str) -> str:
        if not value:
            raise PydanticCustomError("required", "Required")
        return value


class RefreshIn(BaseModel):
    refresh_token: str

    @field_validator("refresh_token")
    @classmethod
    def check_token(cls, value: str) -> str:
        if not value:
            raise PydanticCustomError("required", "Required")
        return value


class GoogleIn(BaseModel):
    code: str
    code_verifier: str
    redirect_uri: str

    @field_validator("code")
    @classmethod
    def check_code(cls, value: str) -> str:
        if not value:
            raise PydanticCustomError("required", "Required")
        return value

    @field_validator("code_verifier")
    @classmethod
    def check_verifier(cls, value: str) -> str:
        if not 43 <= len(value) <= 128:
            raise PydanticCustomError("invalid_verifier", "Invalid code verifier")
        return value

    @field_validator("redirect_uri")
    @classmethod
    def check_redirect(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise PydanticCustomError("invalid_redirect", "Invalid redirect URI")
        return value


class UserOut(BaseModel):
    id: int
    email: str


class TokenOut(BaseModel):
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    user: UserOut


def _token_out(user: User, pair: auth.TokenPair) -> TokenOut:
    return TokenOut(
        access_token=pair.access_token,
        access_expires_at=pair.access_expires_at,
        refresh_token=pair.refresh_token,
        refresh_expires_at=pair.refresh_expires_at,
        user=UserOut(id=user.id, email=user.email),
    )


def _error(status: int, message: str, description: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"message": message, "description": description})


@router.post("/signup", response_model=TokenOut, status_code=201)
def signup(body: SignupIn, db: Session = Depends(get_db)) -> TokenOut:
    if body.email not in settings.allowed_emails:
        raise _error(403, "Sign-ups are invite-only", "This email isn't on the invite list.")
    if auth.get_user_by_email(db, body.email) is not None:
        raise _error(409, "An account with this email already exists", "Log in instead.")
    user = User(email=body.email, password_hash=auth.hash_password(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _error(409, "An account with this email already exists", "Log in instead.") from None
    return _token_out(user, auth.issue_token_pair(db, user))


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    if auth.is_rate_limited(db, body.email):
        raise _error(429, "Too many attempts", "Wait 15 minutes and try again.")
    user = auth.get_user_by_email(db, body.email)
    if user is None:
        auth.verify_unknown_user(body.password)
        ok = False
    else:
        ok = auth.verify_password(user.password_hash, body.password) and user.is_active
    auth.record_attempt(db, body.email, ok)
    if not ok or user is None:
        raise _error(401, "Incorrect email or password", "Check your details and try again.")
    if user.password_hash and auth.needs_rehash(user.password_hash):
        user.password_hash = auth.hash_password(body.password)
    user.last_login_at = datetime.now(UTC)
    db.commit()
    return _token_out(user, auth.issue_token_pair(db, user))


@router.post("/google", response_model=TokenOut)
def google_login(body: GoogleIn, db: Session = Depends(get_db)) -> TokenOut:
    if not settings.google_client_id or not settings.google_client_secret:
        raise _error(503, "Google sign-in isn't configured", "Use your email and password for now.")
    failed = _error(401, "Google sign-in failed", "Try again, or log in with your email.")
    try:
        id_token = google_auth.exchange_code(body.code, body.code_verifier, body.redirect_uri)
        claims = google_auth.verify_id_token(id_token)
        user = google_auth.sign_in_with_google(db, claims, settings.allowed_emails)
    except google_auth.GoogleAuthError:
        raise failed from None
    except google_auth.GoogleEmailNotVerified:
        raise _error(
            403, "Google email not verified", "Verify your email with Google, then try again."
        ) from None
    except google_auth.NotAllowlisted:
        raise _error(403, "Sign-ups are invite-only", "This email isn't on the invite list.") from None
    except google_auth.InactiveUser:
        raise _error(401, "Incorrect email or password", "Check your details and try again.") from None
    except IntegrityError:
        db.rollback()
        raise failed from None
    return _token_out(user, auth.issue_token_pair(db, user))


@router.post("/refresh",response_model=TokenOut)
def refresh(body: RefreshIn, db: Session = Depends(get_db)) -> TokenOut:
    result = auth.rotate_refresh(db, body.refresh_token)
    if result is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    user, pair = result
    return _token_out(user, pair)


@router.post("/logout", response_model=Outcome)
def logout(body: RefreshIn, db: Session = Depends(get_db)) -> Outcome:
    auth.revoke_family(db, body.refresh_token)
    return Outcome(message="Logged out", description="You have been logged out.")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return UserOut(id=user.id, email=user.email)

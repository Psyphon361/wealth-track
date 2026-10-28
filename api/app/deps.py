from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.services import auth


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Resolve the active user from `Authorization: Bearer <access token>`, else 401."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Unauthorized")
    claims = auth.decode_access_token(token.strip())
    if claims is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        user_id = int(claims["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Unauthorized") from None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user

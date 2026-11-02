from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models import User
from app.routers.assets import REGISTRY, _holding_name
from app.routers.portfolio import LABELS
from app.schemas.deleted import DeletedHolding
from app.services.purge import RETENTION_DAYS

router = APIRouter(tags=["deleted"])


def deleted_item(slug: str, obj, now: datetime) -> DeletedHolding:
    purge_on = (obj.deleted_at + timedelta(days=RETENTION_DAYS)).date()
    return DeletedHolding(
        type=slug,
        type_label=LABELS[slug],
        id=obj.id,
        name=_holding_name(obj),
        deleted_at=obj.deleted_at,
        purge_on=purge_on,
        days_left=max(0, (purge_on - now.date()).days),
    )


@router.get("/deleted", response_model=list[DeletedHolding])
def list_deleted(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """The user's holdings deleted within the last 30 days, newest first."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=RETENTION_DAYS)
    items: list[DeletedHolding] = []
    for slug, (model, _create, _read) in REGISTRY.items():
        stmt = (
            select(model)
            .where(model.user_id == user.id, model.deleted_at.is_not(None), model.deleted_at >= cutoff)
            .execution_options(include_deleted=True)
        )
        items.extend(deleted_item(slug, obj, now) for obj in db.scalars(stmt))
    items.sort(key=lambda item: item.deleted_at, reverse=True)
    return items

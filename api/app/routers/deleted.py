from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, literal, select, union_all
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models import User
from app.models.nps import Nps
from app.models.nps_master import NpsMaster
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


def name_expr(model):
    """SQL twin of `_holding_name` (bank + label, scheme name, or name)."""
    if hasattr(model, "bank"):
        return case(
            (func.coalesce(model.label, "") != "", model.bank + " · " + model.label),
            else_=model.bank,
        )
    if model is Nps:
        return NpsMaster.scheme_name
    if hasattr(model, "scheme_name"):
        return model.scheme_name
    return model.name


def deleted_union(user_id: int, cutoff: datetime):
    """One UNION ALL over every holding table: type, id, name, deleted_at."""
    selects = []
    for slug, (model, _create, _read) in REGISTRY.items():
        stmt = select(
            literal(slug).label("type"),
            model.id.label("id"),
            name_expr(model).label("name"),
            model.deleted_at.label("deleted_at"),
        )
        if model is Nps:
            stmt = stmt.join(NpsMaster, NpsMaster.scheme_id == Nps.scheme_id)
        selects.append(
            stmt.where(
                model.user_id == user_id, model.deleted_at.is_not(None), model.deleted_at >= cutoff
            )
        )
    sub = union_all(*selects).subquery()
    return select(sub).order_by(sub.c.deleted_at.desc()).execution_options(include_deleted=True)


@router.get("/deleted", response_model=list[DeletedHolding])
def list_deleted(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """The user's holdings deleted within the last 30 days, newest first."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=RETENTION_DAYS)
    rows = db.execute(deleted_union(user.id, cutoff)).all()
    items = []
    for row in rows:
        purge_on = (row.deleted_at + timedelta(days=RETENTION_DAYS)).date()
        items.append(
            DeletedHolding(
                type=row.type,
                type_label=LABELS[row.type],
                id=row.id,
                name=row.name,
                deleted_at=row.deleted_at,
                purge_on=purge_on,
                days_left=max(0, (purge_on - now.date()).days),
            )
        )
    return items

from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.db import get_db, read_bind
from app.deps import current_user
from app.models.user import User
from app.routers.portfolio import load_groups
from app.schemas.search import SearchIndexResponse
from app.services import search_index

router = APIRouter(tags=["search"])


@router.get("/search/index", response_model=SearchIndexResponse)
def get_search_index(
    response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """Every holding of the user as a flat item; the browser searches and ranks locally."""
    response.headers["Cache-Control"] = "private, no-store"
    bind = read_bind(db)
    # Master rows load concurrently with the valued holdings, each on its own session.
    with ThreadPoolExecutor(max_workers=len(search_index.MASTER_FETCHERS)) as pool:
        futures = {
            name: pool.submit(fetch, bind, user.id)
            for name, fetch in search_index.MASTER_FETCHERS.items()
        }
        groups = load_groups(db, user.id)
        masters = {name: future.result() for name, future in futures.items()}
    return {"items": search_index.build_items(groups, masters)}

import os
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None

SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)


def get_engine() -> Engine:
    """Create the engine on first use so the app can start without DATABASE_URL."""
    global _engine
    if _engine is None:
        if not settings.database_url:
            raise RuntimeError(
                "DATABASE_URL is not set. Copy .env.example to .env and fill it in."
            )
        # Vercel (Fluid compute) reuses instances across concurrent requests, so keep a
        # modest pool: 5 for the concurrent portfolio queries plus a little headroom.
        on_vercel = bool(os.environ.get("VERCEL"))
        _engine = create_engine(
            settings.database_url,
            pool_size=5 if on_vercel else 10,
            max_overflow=3 if on_vercel else 5,
            pool_recycle=240,  # Neon drops idle connections; recycle instead of pre-ping round trips
            # Neon's PgBouncer (transaction pooling) breaks psycopg 3 server-side prepared statements.
            connect_args={"prepare_threshold": None},
        )
        SessionLocal.configure(bind=_engine)
    return _engine


def get_db() -> Iterator[Session]:
    get_engine()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

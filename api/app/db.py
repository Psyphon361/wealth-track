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
        # modest pool: 5 for the concurrent portfolio queries plus a little headroom. Locally
        # the analytics endpoints run ~20 queries at once and a connection opened above the
        # pool size costs ~2.5 s (TLS to Neon), so keep the whole burst pooled.
        on_vercel = bool(os.environ.get("VERCEL"))
        _engine = create_engine(
            settings.database_url,
            pool_size=5 if on_vercel else 24,
            max_overflow=3 if on_vercel else 5,
            pool_recycle=240,  # Neon drops idle connections; recycle instead of pre-ping round trips
            # Neon's PgBouncer (transaction pooling) breaks psycopg 3 server-side prepared statements.
            connect_args={"prepare_threshold": None},
        )
        SessionLocal.configure(bind=_engine)
    return _engine


def read_bind(db: Session) -> Engine:
    """The session's engine in autocommit mode, for read-only queries on their own sessions.

    Autocommit skips the BEGIN and ROLLBACK round trips around every query (3 round trips become
    1); it shares the same connection pool. Never use it for writes. Other databases (the
    in-memory SQLite of the tests, whose threads share one connection) keep the plain engine.
    """
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return bind
    return bind.execution_options(isolation_level="AUTOCOMMIT")


def get_db() -> Iterator[Session]:
    get_engine()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

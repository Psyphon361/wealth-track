from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import read_bind


def test_postgres_bind_is_autocommit():
    engine = create_engine("postgresql+psycopg://u:p@localhost/x")
    with Session(bind=engine) as db:
        bind = read_bind(db)
    assert bind.get_execution_options()["isolation_level"] == "AUTOCOMMIT"
    assert bind.dialect.name == "postgresql"
    assert "isolation_level" not in engine.get_execution_options()


def test_non_postgres_bind_is_unchanged():
    engine = create_engine("sqlite://")
    with Session(bind=engine) as db:
        assert read_bind(db) is engine

"""Migration 0033 adds the column declared on the MFTransaction model."""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa

import app.models  # noqa: F401
from app.db import Base

FILE = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "0033_mf_txn_manual.py"


class Recorder:
    def __init__(self):
        self.added: list[tuple[str, sa.Column]] = []
        self.dropped: list[tuple[str, str]] = []

    def add_column(self, table, column, **kw):
        self.added.append((table, column))

    def drop_column(self, table, column, **kw):
        self.dropped.append((table, column))


@pytest.fixture
def migration(monkeypatch):
    spec = importlib.util.spec_from_file_location("migration_0033", FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rec = Recorder()
    monkeypatch.setattr(module, "op", rec)
    module.rec = rec
    return module


def test_revision_ids(migration):
    assert migration.revision == "0033"
    assert migration.down_revision == "0032"


def test_upgrade_adds_the_model_column(migration):
    migration.upgrade()
    assert len(migration.rec.added) == 1
    table, column = migration.rec.added[0]
    model_column = Base.metadata.tables["mf_transactions"].c.manual
    assert table == "mf_transactions"
    assert column.name == model_column.name == "manual"
    assert isinstance(column.type, sa.Boolean)
    assert column.nullable is False and model_column.nullable is False
    assert column.server_default is not None and model_column.server_default is not None
    assert str(column.server_default.arg) == str(model_column.server_default.arg)


def test_downgrade_drops_it(migration):
    migration.downgrade()
    assert migration.rec.dropped == [("mf_transactions", "manual")]

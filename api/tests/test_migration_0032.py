"""Migration 0032 creates exactly the constraints and index declared on the models."""
import importlib.util
import re
from pathlib import Path

import pytest
from sqlalchemy import CheckConstraint

import app.models  # noqa: F401
from app.db import Base

VERSIONS = Path(__file__).resolve().parent.parent / "alembic" / "versions"
FILE = VERSIONS / "0032_db_constraints.py"
INDEX = "uq_holding_fundings_active"


class Recorder:
    def __init__(self):
        self.checks: dict[str, tuple[str, str]] = {}
        self.indexes: list[dict] = []
        self.drops: list[tuple[str, str, str]] = []
        self.dropped_indexes: list[str] = []

    def create_check_constraint(self, name, table, condition, **kw):
        self.checks[name] = (table, str(condition))

    def create_index(self, name, table, columns, **kw):
        self.indexes.append({"name": name, "table": table, "columns": columns, **kw})

    def drop_constraint(self, name, table, type_=None, **kw):
        self.drops.append((name, table, type_))

    def drop_index(self, name, table_name=None, **kw):
        self.dropped_indexes.append(name)


@pytest.fixture(scope="module")
def migration():
    spec = importlib.util.spec_from_file_location("migration_0032", FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def up(migration, monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(migration, "op", rec)
    migration.upgrade()
    return rec


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).replace('"', "")).strip().lower()


def earlier_names() -> set[str]:
    names: set[str] = set()
    for path in VERSIONS.glob("*.py"):
        if path.name.startswith("0032"):
            continue
        names |= set(re.findall(r"\b(?:ck|uq)_\w+", path.read_text()))
    return names


def model_checks() -> dict[str, tuple[str, str]]:
    old = earlier_names()
    found = {}
    for table in Base.metadata.tables.values():
        for c in table.constraints:
            if isinstance(c, CheckConstraint) and c.name and c.name.startswith("ck_"):
                if c.name not in old:
                    found[c.name] = (table.name, str(c.sqltext))
    return found


def test_revision_ids(migration):
    assert migration.revision == "0032"
    assert migration.down_revision == "0031"


def test_upgrade_creates_the_model_constraints(up):
    models = model_checks()
    assert models, "no new model constraints found"
    assert set(up.checks) == set(models)


def test_upgrade_expressions_and_tables_match_models(up):
    for name, (table, expr) in model_checks().items():
        assert up.checks[name][0] == table, name
        assert norm(up.checks[name][1]) == norm(expr), name


def test_upgrade_creates_the_partial_unique_index(up):
    assert [i["name"] for i in up.indexes] == [INDEX]
    index = up.indexes[0]
    assert index["unique"] is True
    assert index["table"] == "holding_fundings"
    model_index = next(
        i for i in Base.metadata.tables["holding_fundings"].indexes if i.name == INDEX
    )
    assert index["columns"] == [c.name for c in model_index.columns]
    assert norm(index["postgresql_where"]) == norm(model_index.dialect_options["postgresql"]["where"])


def test_downgrade_drops_the_same_names(migration, monkeypatch, up):
    rec = Recorder()
    monkeypatch.setattr(migration, "op", rec)
    migration.downgrade()
    assert {n for n, _t, _k in rec.drops} == set(up.checks)
    assert len(rec.drops) == len(up.checks)
    assert all(kind == "check" for _n, _t, kind in rec.drops)
    assert {(n, t) for n, t, _k in rec.drops} == {(n, t) for n, (t, _e) in up.checks.items()}
    assert rec.dropped_indexes == [INDEX]

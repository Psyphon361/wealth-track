from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from app.models import Cash, FixedDeposit, HoldingExit, Stock
from app.routers.assets import REGISTRY, _holding_name
from app.routers.deleted import deleted_item, deleted_union, name_expr
from app.services import purge
from tests.conftest import make_cash
from tests.test_scoping import FD, client, users  # noqa: F401  (fixtures)

CASH = {"name": "Soft Savings", "kind": "savings", "balance": 25000, "balance_date": "2026-10-01"}


def _utc_ago(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _mark_deleted(engine, model, item_id: int, days_ago: int) -> None:
    with sessionmaker(bind=engine)() as session:
        session.execute(
            update(model).where(model.id == item_id).values(deleted_at=_utc_ago(days_ago))
        )
        session.commit()


def _cash_row(user_id: int, name: str, deleted_days_ago: int | None) -> Cash:
    return Cash(
        user_id=user_id, name=name, kind="savings", balance=1, balance_date=date(2026, 10, 1),
        deleted_at=None if deleted_days_ago is None else _utc_ago(deleted_days_ago),
    )  # fmt: skip


@pytest.fixture
def session(client, auth_engine):  # noqa: F811
    with sessionmaker(bind=auth_engine, expire_on_commit=False)() as s:
        yield s


# --- the global filter ---------------------------------------------------------


def test_filter_covers_entity_column_and_subquery_selects(session):
    session.add_all([_cash_row(1, "live", None), _cash_row(1, "gone", 1)])
    session.commit()

    assert [c.name for c in session.scalars(select(Cash))] == ["live"]
    assert list(session.scalars(select(Cash.name))) == ["live"]
    assert session.execute(select(Cash.id, Cash.name)).all()[0][1] == "live"

    # Subquery over another holding table: user 1 has a live FD, user 2 only a deleted one.
    def fd(user_id: int, deleted_days_ago: int | None) -> FixedDeposit:
        return FixedDeposit(
            user_id=user_id, bank="B", principal=1, rate=1, start_date=date(2026, 10, 1),
            compounding="simple", payout_type="cumulative", tenure_years=1, tenure_months=0,
            tenure_days=0,
            deleted_at=None if deleted_days_ago is None else _utc_ago(deleted_days_ago),
        )  # fmt: skip

    session.add_all([fd(1, None), fd(2, 1), _cash_row(2, "user2", None)])
    session.commit()
    held_users = select(FixedDeposit.user_id)
    assert list(session.scalars(held_users)) == [1]
    stmt = select(Cash.name).where(Cash.user_id.in_(held_users))
    assert list(session.scalars(stmt)) == ["live"]
    with_deleted = held_users.execution_options(include_deleted=True)
    assert sorted(session.scalars(with_deleted)) == [1, 2]


def test_include_deleted_bypasses_filter(session):
    session.add_all([_cash_row(1, "live", None), _cash_row(1, "gone", 1)])
    session.commit()
    stmt = select(Cash.name).order_by(Cash.id).execution_options(include_deleted=True)
    assert list(session.scalars(stmt)) == ["live", "gone"]


# --- delete / restore ----------------------------------------------------------


def test_delete_hides_and_restore_brings_back(client, users):  # noqa: F811
    a, _, _, _ = users
    item_id = client.post("/api/assets/cash", json=CASH, headers=a).json()["id"]
    url = f"/api/assets/cash/{item_id}"

    deleted = client.delete(url, headers=a)
    assert deleted.status_code == 200
    assert deleted.json() == {"message": "Cash & Savings deleted", "description": "Soft Savings"}
    assert client.get(url, headers=a).status_code == 404
    assert client.put(url, json=CASH, headers=a).status_code == 404
    assert client.get("/api/assets/cash", headers=a).json() == []
    assert client.get("/api/holdings/cash", headers=a).json()["total"] == 0

    restored = client.post(f"{url}/restore", headers=a)
    assert restored.status_code == 200
    assert restored.json() == {"message": "Cash & Savings restored", "description": "Soft Savings"}
    assert client.get(url, headers=a).status_code == 200
    assert client.get("/api/holdings/cash", headers=a).json()["total"] == 1


def test_restore_of_live_missing_or_foreign_row_is_404(client, users):  # noqa: F811
    a, _, b, _ = users
    item_id = client.post("/api/assets/cash", json=CASH, headers=a).json()["id"]
    url = f"/api/assets/cash/{item_id}/restore"
    live = client.post(url, headers=a)
    assert live.status_code == 404
    assert live.json()["message"] == "Cash & Savings not found"

    client.delete(f"/api/assets/cash/{item_id}", headers=a)
    foreign = client.post(url, headers=b)
    assert foreign.status_code == 404
    assert foreign.json() == live.json()
    assert client.post("/api/assets/cash/9999/restore", headers=a).status_code == 404
    assert client.post(url, headers=a).status_code == 200


# --- the recently deleted list -------------------------------------------------


def test_deleted_list_window_order_and_days_left(client, users, auth_engine):  # noqa: F811
    a, _, b, _ = users
    old = client.post("/api/assets/cash", json={**CASH, "name": "Old"}, headers=a).json()["id"]
    recent = client.post("/api/assets/cash", json={**CASH, "name": "Recent"}, headers=a).json()["id"]
    fd = client.post("/api/assets/fd", json=FD, headers=a).json()["id"]
    live = client.post("/api/assets/cash", json={**CASH, "name": "Live"}, headers=a).json()["id"]
    other = client.post("/api/assets/cash", json={**CASH, "name": "Theirs"}, headers=b).json()["id"]
    _mark_deleted(auth_engine, Cash, old, 31)
    _mark_deleted(auth_engine, Cash, recent, 5)
    _mark_deleted(auth_engine, FixedDeposit, fd, 1)
    _mark_deleted(auth_engine, Cash, other, 2)
    assert live

    items = client.get("/api/deleted", headers=a).json()
    assert [(i["type"], i["name"]) for i in items] == [
        ("fd", "Scoped Bank"),
        ("cash", "Recent"),
    ]
    assert items[0]["type_label"] == "Fixed Deposits"
    assert items[1]["type_label"] == "Cash & Savings"
    assert items[1]["id"] == recent
    assert items[1]["days_left"] == 25
    assert items[0]["days_left"] == 29
    assert client.get("/api/deleted").status_code == 401


def test_deleted_item_days_left_never_negative():
    now = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
    obj = make_cash(deleted_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
    item = deleted_item("cash", obj, now)
    assert item.purge_on == date(2026, 10, 1)
    assert item.days_left == 0
    fresh = deleted_item("cash", make_cash(deleted_at=now), now)
    assert fresh.purge_on == date(2026, 12, 2)
    assert fresh.days_left == 30


# --- purge ---------------------------------------------------------------------


def test_purge_removes_only_rows_deleted_over_30_days_ago(session):
    session.add_all(
        [
            _cash_row(1, "live", None),
            _cash_row(1, "recent", 5),
            _cash_row(2, "old-a", 31),
            _cash_row(1, "old-b", 90),
        ]
    )
    session.commit()

    counts = purge.purge_deleted(session)

    assert counts["cash"] == 2
    assert sum(n for slug, n in counts.items() if slug != "cash") == 0
    left = select(Cash.name).order_by(Cash.id).execution_options(include_deleted=True)
    assert list(session.scalars(left)) == ["live", "recent"]


def test_purge_removes_the_exit_rows_of_purged_holdings_only(session):
    def stock(name, deleted_days_ago):
        return Stock(
            user_id=1, name=name, exchange="NSE", quantity=10, avg_buy_price=100,
            buy_date=date(2025, 1, 1), deleted_at=_utc_ago(deleted_days_ago) if deleted_days_ago else None,
        )  # fmt: skip

    old, recent = stock("old", 40), stock("recent", 5)
    session.add_all([old, recent])
    session.flush()

    def exit_row(asset_type, holding_id):
        return HoldingExit(
            user_id=1, asset_type=asset_type, holding_id=holding_id, kind="sale",
            exit_date=date(2026, 1, 15), quantity=1, amount=1, cost=1, destination="none",
        )  # fmt: skip

    # Same id under another type must survive: holding_id is only unique within a type.
    session.add_all(
        [exit_row("stock", old.id), exit_row("stock", old.id), exit_row("stock", recent.id),
         exit_row("gold", old.id)]
    )  # fmt: skip
    session.commit()

    counts = purge.purge_deleted(session)

    assert counts["stock"] == 1 and counts["exits"] == 2
    kept = session.scalars(select(HoldingExit).order_by(HoldingExit.id)).all()
    assert [(e.asset_type, e.holding_id) for e in kept] == [
        ("stock", recent.id), ("gold", old.id),
    ]


def test_deleted_union_covers_every_slug():
    sql = str(deleted_union(1, datetime.now(timezone.utc)).compile())
    assert sql.count("UNION ALL") == len(REGISTRY) - 1
    for model, _c, _r in REGISTRY.values():
        assert model.__tablename__ in sql


@pytest.mark.parametrize("label", [None, "", "Tax saver"])
def test_name_expr_matches_holding_name_for_bank_models(client, users, session, label):  # noqa: F811
    a = users[0]
    body = FD if label is None else {**FD, "label": label}
    fd_id = client.post("/api/assets/fd", json=body, headers=a).json()["id"]
    fd = session.get(FixedDeposit, fd_id)
    name = session.scalar(select(name_expr(FixedDeposit)).where(FixedDeposit.id == fd_id))
    assert name == _holding_name(fd)
    assert (" · " in name) == bool(fd.label)

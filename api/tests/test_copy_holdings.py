from datetime import datetime

from app.jobs.copy_holdings import (
    build_insert,
    business_key,
    is_duplicate,
    relink_master,
    relink_scheme,
)
from tests.conftest import make_bond, make_fd, make_stock


def _row(obj, **extra):
    row = dict(vars(obj))
    row.update(extra)
    return row


def test_relink_master_hit_for_stock_bond_and_issuer():
    # same function serves stock/bond (ISIN) and FD/RD issuer (code) maps
    assert relink_master(5, {5: "INE001A01036"}, {"INE001A01036": 90}) == (90, False)
    assert relink_master(6, {6: "IN0020200001"}, {"IN0020200001": 7}) == (7, False)
    assert relink_master(7, {7: "HDFC"}, {"HDFC": 3}) == (3, False)


def test_relink_master_miss_and_no_link():
    assert relink_master(5, {5: "INE001A01036"}, {}) == (None, True)
    assert relink_master(5, {}, {"X": 1}) == (None, True)
    assert relink_master(None, {5: "X"}, {"X": 1}) == (None, False)


def test_relink_scheme_kept_or_nulled():
    assert relink_scheme(119551, {119551, 1}) == (119551, False)
    assert relink_scheme(119551, {1}) == (None, True)
    assert relink_scheme(None, {1}) == (None, False)


def test_duplicate_detection():
    stock = make_stock(master_id=1)
    existing = {business_key(_row(stock), "master_id")}
    # different id, user, link and timestamps are ignored
    same = _row(make_stock(master_id=99), user_id=7, created_at=datetime(2030, 1, 1))
    assert is_duplicate(same, "master_id", existing)
    # a differing business field is not a duplicate
    assert not is_duplicate(_row(make_stock(quantity=11)), "master_id", existing)
    assert not is_duplicate(_row(make_stock(name="Other")), "master_id", existing)


def test_duplicate_detection_other_tables():
    fd = make_fd(issuer_id=1)
    assert is_duplicate(_row(make_fd(issuer_id=None)), "issuer_id", {business_key(_row(fd), "issuer_id")})
    bond = make_bond(master_id=1)
    assert not is_duplicate(
        _row(make_bond(isin="X")), "master_id", {business_key(_row(bond), "master_id")}
    )


def test_build_insert_excludes_id_swaps_user_keeps_timestamps():
    stamp = datetime(2024, 5, 5)
    row = _row(make_stock(master_id=1), user_id=1, created_at=stamp, updated_at=stamp)
    values = build_insert(row, 42, "master_id", 77)
    assert "id" not in values
    assert values["user_id"] == 42
    assert values["master_id"] == 77
    assert values["created_at"] == stamp and values["updated_at"] == stamp
    assert values["name"] == row["name"]

"""One-off: copy one user's holdings from a source DB to a target DB.

    SOURCE_DATABASE_URL=... TARGET_DATABASE_URL=... \
        python -m app.jobs.copy_holdings --email you@example.com [--target-email other@example.com] [--apply]

SOURCE_DATABASE_URL defaults to DATABASE_URL from api/.env; TARGET_DATABASE_URL is required.
Without --apply nothing is written (dry run). Connection URLs are never printed.
Master links are re-linked by natural key (ISIN, issuer code, scheme code); a holding whose
master row is missing in the target is copied with the link set to NULL and reported.
"""

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, create_engine, insert, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import settings
from app.models.bond import Bond
from app.models.bond_master import BondMaster
from app.models.fd_issuer_master import FdIssuerMaster
from app.models.fixed_deposit import FixedDeposit
from app.models.mf_master import MFMaster
from app.models.mutual_fund import MutualFund
from app.models.recurring_deposit import RecurringDeposit
from app.models.stock import Stock
from app.models.stock_master import StockMaster
from app.services import auth

NON_BUSINESS = ("id", "user_id", "created_at", "updated_at")


@dataclass(frozen=True)
class TableSpec:
    model: Any
    name_column: str
    link_column: str
    master: Any  # master model, or MFMaster (scheme_code kept as-is)
    key_column: str  # natural key column on the master


TABLES = (
    TableSpec(FixedDeposit, "bank", "issuer_id", FdIssuerMaster, "code"),
    TableSpec(RecurringDeposit, "bank", "issuer_id", FdIssuerMaster, "code"),
    TableSpec(Stock, "name", "master_id", StockMaster, "isin"),
    TableSpec(Bond, "name", "master_id", BondMaster, "isin"),
    TableSpec(MutualFund, "scheme_name", "scheme_code", MFMaster, "scheme_code"),
)


# ---- pure logic (no DB) ----------------------------------------------------------------


def relink_master(
    source_id: int | None,
    source_keys: dict[int, str],
    target_ids: dict[str, int],
) -> tuple[int | None, bool]:
    """Map a source master id to the target master id via the natural key.

    Returns (new_id, unmatched). No source link -> (None, False). A link whose key is
    unknown in the target -> (None, True).
    """
    if source_id is None:
        return None, False
    key = source_keys.get(source_id)
    new_id = target_ids.get(key) if key is not None else None
    return new_id, new_id is None


def relink_scheme(scheme_code: int | None, target_codes: set[int]) -> tuple[int | None, bool]:
    """MF scheme_code is the natural key: keep it only if the target has that scheme."""
    if scheme_code is None:
        return None, False
    if scheme_code in target_codes:
        return scheme_code, False
    return None, True


def business_key(row: dict[str, Any], link_column: str) -> tuple:
    """Values of every column except id, user_id, timestamps and the master link."""
    skip = set(NON_BUSINESS) | {link_column}
    return tuple(sorted((k, v) for k, v in row.items() if k not in skip))


def is_duplicate(row: dict[str, Any], link_column: str, existing_keys: set[tuple]) -> bool:
    return business_key(row, link_column) in existing_keys


def build_insert(
    row: dict[str, Any], target_user_id: int, link_column: str, new_link: int | None
) -> dict[str, Any]:
    """Insert values: all columns but id, user_id swapped, link replaced, timestamps kept."""
    values = {k: v for k, v in row.items() if k != "id"}
    values["user_id"] = target_user_id
    values[link_column] = new_link
    return values


# ---- I/O -------------------------------------------------------------------------------


def _normalise(url: str) -> str:
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _engine(url: str) -> Engine:
    return create_engine(_normalise(url), connect_args={"prepare_threshold": None})


def _row_dict(model: Any, obj: Any) -> dict[str, Any]:
    return {c.key: getattr(obj, c.key) for c in model.__table__.columns}


def _find_user(session: Session, label: str, raw_email: str):
    user = auth.get_user_by_email(session, auth.normalise_email(raw_email))
    if user is None:
        sys.exit(f"No user with that email in the {label} database")
    if not user.is_active:
        sys.exit(f"The user in the {label} database is inactive")
    return user


def _lookup_maps(spec: TableSpec, source: Session, target: Session, src_rows: list[dict]):
    link = spec.link_column
    used = {r[link] for r in src_rows if r[link] is not None}
    if spec.master is MFMaster:
        if not used:
            return None, set()
        found = target.scalars(select(MFMaster.scheme_code).where(MFMaster.scheme_code.in_(used)))
        return None, set(found)
    if not used:
        return {}, {}
    key_col = getattr(spec.master, spec.key_column)
    source_keys = dict(source.execute(select(spec.master.id, key_col).where(spec.master.id.in_(used))).all())
    keys = {k for k in source_keys.values() if k is not None}
    target_ids = {}
    if keys:
        rows = target.execute(select(spec.master.id, key_col).where(key_col.in_(keys))).all()
        target_ids = {k: i for i, k in rows}
    return source_keys, target_ids


def copy_table(spec: TableSpec, source: Session, target: Session, src_uid: int, tgt_uid: int):
    """Return (found, inserts, duplicates, listing) where listing is [(action, name)]."""
    model = spec.model
    link = spec.link_column
    src_rows = [
        _row_dict(model, o)
        for o in source.scalars(select(model).where(model.user_id == src_uid).order_by(model.id))
    ]
    existing = {
        business_key(_row_dict(model, o), link)
        for o in target.scalars(select(model).where(model.user_id == tgt_uid))
    }
    source_keys, target_ids = _lookup_maps(spec, source, target, src_rows)
    inserts, duplicates, listing = [], 0, []
    for row in src_rows:
        name = str(row[spec.name_column])
        if is_duplicate(row, link, existing):
            duplicates += 1
            listing.append(("skip (duplicate)", name))
            continue
        if spec.master is MFMaster:
            new_link, missing = relink_scheme(row[link], target_ids)
        else:
            new_link, missing = relink_master(row[link], source_keys, target_ids)
        listing.append(("copy (link not found)" if missing else "copy", name))
        inserts.append(build_insert(row, tgt_uid, link, new_link))
    return len(src_rows), inserts, duplicates, listing


def _scrub(message: str, urls: list[str]) -> str:
    for url in urls:
        try:
            password = make_url(url).password
        except Exception:
            password = None
        message = message.replace(url, "***")
        if password:
            message = message.replace(password, "***")
    return message[:300]


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.jobs.copy_holdings")
    parser.add_argument("--email", required=True, help="source user email")
    parser.add_argument("--target-email", help="target user email (default: --email)")
    parser.add_argument("--apply", action="store_true", help="write to the target (default: dry run)")
    args = parser.parse_args()

    source_url = os.environ.get("SOURCE_DATABASE_URL") or settings.database_url
    target_url = os.environ.get("TARGET_DATABASE_URL")
    if not source_url:
        sys.exit("Set SOURCE_DATABASE_URL (or DATABASE_URL in api/.env)")
    if not target_url:
        sys.exit("Set TARGET_DATABASE_URL")

    source_engine, target_engine = _engine(source_url), _engine(target_url)
    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"{mode}: copying holdings from source to target")
    try:
        with Session(source_engine) as source, Session(target_engine) as target:
            src_user = _find_user(source, "source", args.email)
            tgt_user = _find_user(target, "target", args.target_email or args.email)
            verb = "copied" if args.apply else "would copy"
            plans = []
            for spec in TABLES:
                found, inserts, dups, listing = copy_table(
                    spec, source, target, src_user.id, tgt_user.id
                )
                plans.append((spec, inserts))
                table = spec.model.__tablename__
                print(
                    f"{table}: found {found}, {verb} {len(inserts)}, "
                    f"skipped duplicates {dups}, "
                    f"unmatched links {sum(a == 'copy (link not found)' for a, _ in listing)}"
                )
                for action, name in listing:
                    print(f"  {action}: {name}")
            if args.apply:
                for spec, inserts in plans:
                    if inserts:
                        target.execute(insert(spec.model.__table__), inserts)
                target.commit()
            else:
                target.rollback()
    except SystemExit:
        raise
    except Exception as exc:  # roll back (session close) and fail loudly, without URLs
        urls = [u for url in (source_url, target_url) for u in (url, _normalise(url))]
        sys.exit(f"Failed, nothing was written: {type(exc).__name__}: {_scrub(str(exc), urls)}")
    finally:
        source_engine.dispose()
        target_engine.dispose()


if __name__ == "__main__":
    main()

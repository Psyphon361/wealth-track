from collections import defaultdict
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db, read_bind
from app.deps import current_user
from app.models import (
    Bond,
    Gold,
    HoldingExit,
    MFMaster,
    MFTransaction,
    MutualFund,
    Other,
    Stock,
    StockMaster,
)
from app.models.user import User
from app.routers.analytics_tax import _fetch_bond_masters
from app.routers.portfolio import load_groups
from app.schemas.analytics_gains import AnalyticsGains
from app.services import analytics_tax, bond_schedule
from app.services import capital_gains as cg
from app.services.analytics_tax import fy_bounds, fy_label
from app.services.capital_gains import MfTxn, SaleInput

router = APIRouter(tags=["analytics"])

SALE_TYPES = ("stock", "bond", "mf", "gold", "other")


def _by_id(session: Session, model: Any, ids: set[int], key: str = "id") -> dict[Any, Any]:
    if not ids:
        return {}
    column = getattr(model, key)
    return {getattr(r, key): r for r in session.scalars(select(model).where(column.in_(ids)))}


def _master_rows(session: Session, columns: list[Any], key: Any, ids: set[Any]) -> dict[Any, Any]:
    """Master rows (only the given columns) keyed by `key`."""
    if not ids:
        return {}
    return {r[0]: r for r in session.execute(select(key, *columns).where(key.in_(ids)))}


def _sale_input(
    exit_row: HoldingExit,
    holding: Any,
    masters: dict[str, dict[Any, Any]],
    txns: dict[int, list[MfTxn]],
) -> SaleInput:
    kind = exit_row.asset_type
    base: dict[str, Any] = {
        "exit_id": exit_row.id,
        "asset_type": kind,
        "holding_id": exit_row.holding_id,
        "sold_on": exit_row.exit_date,
        "quantity": exit_row.quantity,
        "proceeds": exit_row.amount,
        "cost": exit_row.cost,
    }
    if kind == "stock":
        master = masters["stock"].get(holding.master_id)
        return SaleInput(
            **base,
            name=holding.name,
            bought_on=holding.buy_date,
            stock_kind=master.kind if master else None,
        )
    if kind == "bond":
        master = masters["bond"].get(holding.master_id)
        return SaleInput(
            **base,
            name=holding.name,
            bought_on=holding.purchase_date,
            bond_type=master.bond_type if master else holding.bond_type,
            bond_has_master=master is not None,
        )
    if kind == "mf":
        master = masters["mf"].get(holding.scheme_code)
        return SaleInput(
            **base,
            name=holding.scheme_name,
            bought_on=holding.purchase_date,
            mf_category=master.category if master else holding.category,
            amfi_category=master.amfi_category if master else None,
            mf_txns=txns.get(holding.id, []),
            mf_transaction_id=exit_row.mf_transaction_id,
        )
    if kind == "gold":
        return SaleInput(**base, name=holding.name, bought_on=holding.purchase_date)
    return SaleInput(
        **base,
        name=holding.name,
        bought_on=holding.acquired_on,
        other_category=holding.category,
    )


@router.get("/analytics/capital-gains", response_model=AnalyticsGains)
def get_capital_gains(
    fy: Annotated[int | None, Query()] = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Capital gains and estimated tax on the user's sales for a financial year; bond repayments
    count from the holding whether or not they were settled (SPEC §9)."""
    today = date.today()
    bind = read_bind(db)
    with Session(bind, autoflush=False, expire_on_commit=False) as session:
        exits = list(
            session.scalars(
                select(HoldingExit).where(
                    HoldingExit.user_id == user.id,
                    HoldingExit.asset_type.in_(SALE_TYPES),
                    HoldingExit.kind.in_(("sale", "maturity")),
                )
            )
        )
        bonds = list(session.scalars(select(Bond).where(Bond.user_id == user.id)))
        ids: dict[str, set[int]] = defaultdict(set)
        for e in exits:
            if e.kind == "sale" and e.asset_type != "bond":
                ids[e.asset_type].add(e.holding_id)
        holdings = {
            "stock": _by_id(session, Stock, ids["stock"]),
            "bond": {b.id: b for b in bonds},
            "mf": _by_id(session, MutualFund, ids["mf"]),
            "gold": _by_id(session, Gold, ids["gold"]),
            "other": _by_id(session, Other, ids["other"]),
        }
        # Exits whose holding is soft-deleted or missing are skipped. A bond's maturity exit is
        # read only for the settled amount of an SGB maturity.
        sale_exits = [
            e for e in exits if e.kind == "sale" and e.holding_id in holdings[e.asset_type]
        ]
        settled_by_bond: dict[int, HoldingExit] = {}
        for e in sorted(exits, key=lambda e: (e.exit_date, e.id)):
            if e.kind == "maturity" and e.asset_type == "bond" and e.holding_id in holdings["bond"]:
                settled_by_bond[e.holding_id] = e
        # A bond closed by a full Sell is covered by that sale.
        open_bonds = [b for b in bonds if b.closed_on is None]
        years = cg.available_fys(
            today, [e.exit_date for e in sale_exits], [b.maturity_date for b in open_bonds]
        )
        allowed = [y["start_year"] for y in years]
        start_year = fy if fy is not None else next(y["start_year"] for y in years if y["is_current"])
        if start_year not in allowed:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Invalid financial year",
                    "description": "Choose a financial year from the list.",
                },
            )
        first, last = fy_bounds(start_year)
        sales_exits = [e for e in sale_exits if first <= e.exit_date <= last]

        h = holdings
        bond_masters = _fetch_bond_masters(bind, user.id) if bonds else {}
        masters = {
            "stock": _master_rows(
                session,
                [StockMaster.kind],
                StockMaster.id,
                {h["stock"][e.holding_id].master_id for e in sales_exits if e.asset_type == "stock"}
                - {None},
            ),
            "bond": bond_masters,
            "mf": _master_rows(
                session,
                [MFMaster.category, MFMaster.amfi_category],
                MFMaster.scheme_code,
                {h["mf"][e.holding_id].scheme_code for e in sales_exits if e.asset_type == "mf"}
                - {None},
            ),
        }
        mf_ids = {e.holding_id for e in sales_exits if e.asset_type == "mf"}
        txns: dict[int, list[MfTxn]] = defaultdict(list)
        if mf_ids:
            for t in session.scalars(
                select(MFTransaction).where(MFTransaction.mutual_fund_id.in_(mf_ids))
            ):
                txns[t.mutual_fund_id].append(MfTxn(t.id, t.txn_date, t.kind, t.units, t.amount))

    inputs = [_sale_input(e, h[e.asset_type][e.holding_id], masters, txns) for e in sales_exits]

    tax_free_items: list[dict[str, Any]] = []
    bonds_no_face = 0
    for bond in open_bonds:
        if not first <= bond.maturity_date <= last:
            continue
        master = bond_masters.get(bond.master_id)
        exit_row = settled_by_bond.get(bond.id)
        settled = None
        if exit_row is not None:
            settled = {
                "id": exit_row.id,
                "amount": exit_row.amount,
                "cost": exit_row.cost,
                "date": exit_row.exit_date,
            }
        kind, value = cg.bond_repayment(bond, master, settled)
        if kind == "sale":
            inputs.append(value)
        elif kind == "tax_free":
            if bond.maturity_date <= today:
                tax_free_items.append(value)
        else:
            future_sgb_maturity = (
                bond_schedule.is_sgb(bond, master)
                and not bond_schedule.is_planned_sale(bond, master)
                and bond.maturity_date > today
            )
            if not future_sgb_maturity:
                bonds_no_face += 1
    tax_free_items.sort(
        key=lambda i: (i["settled_on"], i["exit_id"] or 0, i["holding_id"]), reverse=True
    )

    result = cg.capital_gains(inputs, start_year, today)
    sales = sorted(result["sales"], key=cg.sale_order, reverse=True)

    bond_interest = None
    if bonds and start_year in {f["start_year"] for f in analytics_tax.available_fys(today)}:
        groups = load_groups(db, user.id, today)
        overview = analytics_tax.tax_overview(groups, {}, today, start_year, bond_masters)
        row = next((r for r in overview["by_class"] if r["type"] == "bond"), None)
        if row is not None:
            bond_interest = {
                k: row[k]
                for k in ("interest_to_date", "interest_projected", "tds_estimate", "holdings_count")
            }

    return {
        "fy": fy_label(start_year),
        "fy_start": first,
        "fy_end": last,
        "as_of": today,
        "is_current": any(y["is_current"] and y["start_year"] == start_year for y in years),
        "available_fys": years,
        "summary": result["summary"],
        "buckets": result["buckets"],
        "sales": sales,
        "expected": result["expected"],
        "expected_gain": result["expected_gain"],
        "tax_free": {
            "total": sum((i["amount"] for i in tax_free_items), cg.money(0)),
            "items": tax_free_items,
        },
        "bond_interest": bond_interest,
        "excluded": {
            "bonds_no_face": bonds_no_face,
            "no_purchase_date": sum(1 for s in sales if "no_purchase_date" in s["flags"]),
            "old_rules": sum(1 for s in sales if "old_rules" in s["flags"]),
        },
    }

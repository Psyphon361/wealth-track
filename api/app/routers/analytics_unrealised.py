from collections import defaultdict
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db, read_bind
from app.deps import current_user
from app.models import MFMaster, MFTransaction, StockMaster
from app.models.user import User
from app.routers.analytics_gains import _master_rows, get_capital_gains
from app.routers.analytics_tax import _fetch_bond_masters
from app.routers.portfolio import load_records_and_groups
from app.schemas.analytics_unrealised import AnalyticsUnrealised
from app.services import bond_schedule
from app.services import unrealised as un
from app.services.capital_gains import MfTxn, bond_repayment
from app.services.unrealised import HoldingInput

router = APIRouter(tags=["analytics"])


@router.get("/analytics/unrealised", response_model=AnalyticsUnrealised)
def get_unrealised(
    fy: Annotated[int | None, Query()] = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """What the user's open holdings would be taxed as if closed in full today at their current
    value (informational, SPEC §9). `fy` only selects the financial year whose realised usage of
    the equity long-term exemption is shown; the unrealised side is always as of today."""
    realised = get_capital_gains(fy=fy, db=db, user=user)
    today = realised["as_of"]
    start_year = int(realised["fy"][:4])
    records, groups = load_records_and_groups(db, user.id, today)
    items = {g["type"]: {i["id"]: i for i in g["items"]} for g in groups}

    bind = read_bind(db)
    with Session(bind, autoflush=False, expire_on_commit=False) as session:
        bond_masters = _fetch_bond_masters(bind, user.id) if records["bond"] else {}
        stock_masters = _master_rows(
            session,
            [StockMaster.kind],
            StockMaster.id,
            {r.master_id for r in records["stock"] if r.master_id is not None},
        )
        mf_masters = _master_rows(
            session,
            [MFMaster.category, MFMaster.amfi_category],
            MFMaster.scheme_code,
            {r.scheme_code for r in records["mf"] if r.scheme_code is not None},
        )
        mf_ids = {r.id for r in records["mf"] if r.closed_on is None}
        txns: dict[int, list[MfTxn]] = defaultdict(list)
        if mf_ids:
            for t in session.scalars(
                select(MFTransaction).where(MFTransaction.mutual_fund_id.in_(mf_ids))
            ):
                txns[t.mutual_fund_id].append(MfTxn(t.id, t.txn_date, t.kind, t.units, t.amount))

    inputs: list[HoldingInput] = []
    at_cost = 0
    no_invested_amount = 0
    bonds_no_face = 0

    def amounts(item: dict[str, Any]) -> tuple[Decimal, Decimal]:
        return Decimal(str(item["invested"])), Decimal(str(item["current_value"]))

    for r in records["stock"]:
        item = items["stock"][r.id]
        if r.closed_on is not None or item["status"] != "active":
            continue
        if item["price"] is None:
            at_cost += 1
            continue
        cost, value = amounts(item)
        master = stock_masters.get(r.master_id)
        inputs.append(
            HoldingInput(
                "stock", r.id, r.name, Decimal(str(r.quantity)), cost, value, r.buy_date,
                stock_kind=master.kind if master else None,
            )  # fmt: skip
        )
    for r in records["bond"]:
        item = items["bond"][r.id]
        if r.closed_on is not None or item["status"] != "active":
            continue
        master = bond_masters.get(r.master_id)
        kind, _ = bond_repayment(r, master)
        if kind == "no_face":
            future_sgb_maturity = (
                bond_schedule.is_sgb(r, master)
                and not bond_schedule.is_planned_sale(r, master)
                and r.maturity_date > today
            )
            if not future_sgb_maturity:
                bonds_no_face += 1
                continue
        cost, value = amounts(item)
        inputs.append(
            HoldingInput(
                "bond", r.id, r.name, Decimal(str(r.quantity)), cost, value, r.purchase_date,
                bond_type=master.bond_type if master else r.bond_type,
                bond_has_master=master is not None,
                estimated=True,
            )  # fmt: skip
        )
    for r in records["mf"]:
        item = items["mf"][r.id]
        if r.closed_on is not None or item["status"] != "active":
            continue
        if item["nav"] is None:
            at_cost += 1
            continue
        cost, value = amounts(item)
        master = mf_masters.get(r.scheme_code)
        inputs.append(
            HoldingInput(
                "mf", r.id, r.scheme_name, Decimal(str(r.units)), cost, value, r.purchase_date,
                mf_category=master.category if master else r.category,
                amfi_category=master.amfi_category if master else None,
                mf_txns=txns.get(r.id, []),
            )  # fmt: skip
        )
    for r in records["gold"]:
        item = items["gold"][r.id]
        if r.closed_on is not None or item["status"] != "active":
            continue
        if item["rate_per_gram"] is None:
            at_cost += 1
            continue
        cost, value = amounts(item)
        inputs.append(
            HoldingInput(
                "gold", r.id, r.name, Decimal(str(r.weight_grams)), cost, value, r.purchase_date
            )  # fmt: skip
        )
    for r in records["other"]:
        item = items["other"][r.id]
        if r.closed_on is not None or item["status"] != "active":
            continue
        if r.invested_amount is None:
            no_invested_amount += 1
            continue
        cost, value = amounts(item)
        inputs.append(
            HoldingInput(
                "other", r.id, r.name, None, cost, value, r.acquired_on,
                other_category=r.category,
            )  # fmt: skip
        )

    holdings = [un.build_holding(h, today) for h in inputs]
    holdings.sort(key=lambda h: (-h["value"], h["asset_type"], h["holding_id"]))
    report = un.build_report(holdings, start_year, today, realised["buckets"])
    return {
        "fy": realised["fy"],
        "fy_start": realised["fy_start"],
        "fy_end": realised["fy_end"],
        "as_of": today,
        "is_current": realised["is_current"],
        "available_fys": realised["available_fys"],
        **report,
        "holdings": holdings,
        "excluded": {
            "at_cost": at_cost,
            "no_invested_amount": no_invested_amount,
            "bonds_no_face": bonds_no_face,
            "no_purchase_date": sum(
                1 for h in holdings for lot in h["lots"] if lot["bought_on"] is None
                and h["class"] != "crypto"
            ),
        },
    }

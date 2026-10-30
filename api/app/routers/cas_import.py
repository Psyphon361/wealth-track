from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models import MFMaster, MutualFund, User
from app.schemas.assets import MutualFundCreate
from app.schemas.cas_import import CasCommit, CasCommitResult, CasPreview
from app.services import cas_import

router = APIRouter(prefix="/import/cas", tags=["import"])


def _reject(status: int, message: str, description: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"message": message, "description": description})


@router.post("/preview", response_model=CasPreview)
def preview(
    file: UploadFile = File(...),
    password: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    raw = file.file.read(cas_import.MAX_FILE_BYTES + 1)
    if len(raw) > cas_import.MAX_FILE_BYTES:
        raise _reject(413, "File too large", "Upload a CAS PDF smaller than 4 MB.")
    if not raw.startswith(b"%PDF"):
        raise _reject(422, "Couldn't read this statement", "Upload a CAMS or KFintech CAS PDF.")

    data = cas_import.read_statement(raw, password)

    codes, isins = cas_import.cas_codes_and_isins(data)
    conditions = []
    if codes:
        conditions.append(MFMaster.scheme_code.in_(codes))
    if isins:
        conditions.append(MFMaster.isin_growth_payout.in_(isins))
        conditions.append(MFMaster.isin_reinvest.in_(isins))
    masters = db.scalars(select(MFMaster).where(or_(*conditions))).all() if conditions else []
    by_code, by_isin = cas_import.master_lookups(masters)

    matched_codes = {m.scheme_code for m in masters}
    existing_by_code: dict[int, list] = {}
    if matched_codes:
        holdings = db.scalars(
            select(MutualFund)
            .where(MutualFund.user_id == user.id, MutualFund.scheme_code.in_(matched_codes))
            .order_by(MutualFund.id)
        ).all()
        for holding in holdings:
            existing_by_code.setdefault(holding.scheme_code, []).append(holding)

    rows, hidden_zero = cas_import.build_rows(data, by_code, by_isin, existing_by_code)
    period = data.statement_period
    return {
        "statement_from": cas_import._as_date(period.from_),
        "statement_to": cas_import._as_date(period.to),
        "rows": rows,
        "hidden_zero": hidden_zero,
    }


def _field_label(loc) -> str | None:
    fields = [part for part in loc if isinstance(part, str)]
    if not fields:
        return None
    name = fields[-1]
    return "Average NAV" if name == "avg_nav" else name.replace("_", " ").capitalize()


@router.post("/commit", response_model=CasCommitResult)
def commit(
    body: CasCommit,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    title = "Couldn't import — nothing was saved"
    prepared = []
    seen_holdings: set[int] = set()
    for row in body.rows:
        name = row.scheme_name
        try:
            payload = MutualFundCreate(
                scheme_name=row.scheme_name, scheme_code=row.scheme_code, category=row.category,
                units=row.units, avg_nav=row.avg_nav, invested_amount=row.invested_amount,
                purchase_date=row.purchase_date,
            )  # fmt: skip
        except ValidationError as exc:
            error = exc.errors()[0]
            label = _field_label(error.get("loc", ()))
            text = f"{label}: {error['msg']}" if label else str(error["msg"])
            raise _reject(422, title, f"{name} — {text}")

        scheme = db.get(MFMaster, row.scheme_code) if 1 <= row.scheme_code <= 10**9 else None
        if scheme is None:
            raise _reject(422, title, f"{name} — Not found in the AMFI scheme list")

        holding = None
        if row.action == "update":
            if row.holding_id is not None and row.holding_id not in seen_holdings:
                holding = db.scalars(
                    select(MutualFund).where(
                        MutualFund.id == row.holding_id, MutualFund.user_id == user.id
                    )
                ).first()
            if holding is None:
                raise _reject(422, title, f"{name} — The existing holding wasn't found")
            seen_holdings.add(holding.id)
        prepared.append((holding, payload, scheme))

    created = updated = 0
    for holding, payload, scheme in prepared:
        if holding is None:
            db.add(
                MutualFund(
                    **payload.model_dump(exclude={"scheme_name"}),
                    scheme_name=scheme.name[:200],
                    user_id=user.id,
                )
            )
            created += 1
        else:
            holding.units = payload.units
            holding.avg_nav = payload.avg_nav
            holding.invested_amount = payload.invested_amount
            holding.purchase_date = payload.purchase_date
            updated += 1
    db.commit()

    total = created + updated
    return CasCommitResult(
        message=f"Imported {total} fund{'' if total == 1 else 's'}",
        description=f"{created} added, {updated} updated.",
        created=created,
        updated=updated,
    )

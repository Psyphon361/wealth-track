"""Monthly mutual fund SIPs: due-date maths and the posting of instalments.

Each active SIP adds one instalment a month, on its day of month, at the NAV of that day (the next
business day's NAV when the fund publishes none, e.g. a weekend or holiday). The date maths is in
small pure functions (`due_dates`, `next_due`, `units_for`); `post_due` is the only writer.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.mf_master import MFMaster, MFNavHistory, MFNavHistorySync, MFNavLatest
from app.models.mf_sip import MfSip, MfSipSkip
from app.models.mf_transaction import MFTransaction
from app.models.mutual_fund import MutualFund
from app.services import nav_history

logger = logging.getLogger(__name__)

# 0.005% stamp duty is deducted from every instalment before units are allotted.
STAMP_DUTY_FACTOR = Decimal("0.99995")
UNITS_DP = Decimal("0.001")
NAV_DP = Decimal("0.0001")
MONEY_DP = Decimal("0.01")
# A scheme's NAV history is refetched at most this often while an instalment waits for its NAV.
HISTORY_REFETCH_AFTER = timedelta(hours=6)
# Longest run of non-trading days accepted between a due date and the NAV used for it.
MAX_NAV_GAP = timedelta(days=10)
IST = timezone(timedelta(hours=5, minutes=30))

ACTIVE = "active"
PAUSED = "paused"
STOPPED = "stopped"


# --- Pure helpers --------------------------------------------------------------


def today_ist() -> date:
    return datetime.now(IST).date()


def _next_month(day: date) -> date:
    return date(day.year + 1, 1, day.day) if day.month == 12 else date(day.year, day.month + 1, day.day)


def first_due_on_or_after(day_of_month: int, on: date) -> date:
    """The first date on or after `on` that falls on `day_of_month` (1-28, so it exists every month)."""
    if on.day <= day_of_month:
        return date(on.year, on.month, day_of_month)
    return _next_month(date(on.year, on.month, day_of_month))


def due_dates(
    day_of_month: int,
    from_date: date,
    until: date,
    end_date: date | None = None,
    skipped: set[date] | frozenset[date] = frozenset(),
    after: date | None = None,
) -> list[date]:
    """Due dates in [from_date, until], not after end_date, minus skipped dates.

    `after` (the last instalment already posted) excludes that date and everything before it.
    """
    last = min(until, end_date) if end_date is not None else until
    start = from_date if after is None else max(from_date, after + timedelta(days=1))
    current = first_due_on_or_after(day_of_month, start)
    dates: list[date] = []
    while current <= last:
        if current not in skipped:
            dates.append(current)
        current = _next_month(current)
    return dates


def next_due(
    day_of_month: int,
    today: date,
    post_from: date,
    end_date: date | None = None,
    last_posted_on: date | None = None,
) -> date | None:
    """The next instalment date (skips are not applied), or None when the SIP has ended."""
    start = max(today, post_from)
    if last_posted_on is not None:
        start = max(start, last_posted_on + timedelta(days=1))
    candidate = first_due_on_or_after(day_of_month, start)
    if end_date is not None and candidate > end_date:
        return None
    return candidate


def units_for(amount: Decimal, nav: Decimal) -> Decimal:
    """Units allotted for one instalment: amount less 0.005% stamp duty, over the NAV, 3 dp."""
    return (amount * STAMP_DUTY_FACTOR / nav).quantize(UNITS_DP, rounding=ROUND_HALF_UP)


def ordinal(day: int) -> str:
    suffix = "th" if 10 <= day % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def format_inr(amount: Decimal) -> str:
    """₹5,000 or ₹1,25,000.50 (Indian digit grouping, paise only when present)."""
    value = Decimal(str(amount)).quantize(MONEY_DP)
    whole, _, paise = f"{abs(value):.2f}".partition(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    text = ",".join([*groups, tail]) if groups else tail
    if paise != "00":
        text += f".{paise}"
    return f"₹{text}"


def schedule_text(amount: Decimal, day_of_month: int) -> str:
    return f"{format_inr(amount)} on the {ordinal(day_of_month)} of every month"


# --- NAV lookup ----------------------------------------------------------------


def _first_nav_on_or_after(session: Session, scheme_code: int, due: date) -> tuple[date, Decimal] | None:
    row = session.execute(
        sa.select(MFNavHistory.nav_date, MFNavHistory.nav)
        .where(MFNavHistory.scheme_code == scheme_code, MFNavHistory.nav_date >= due)
        .order_by(MFNavHistory.nav_date)
        .limit(1)
    ).first()
    return (row[0], Decimal(str(row[1]))) if row else None


def ensure_history(session: Session, scheme_code: int) -> None:
    """Fetch the scheme's NAV history from mfapi.in when never synced or last synced > 6 h ago.

    Failures are logged and swallowed: the instalment simply waits for the next run.
    """
    now = datetime.now(timezone.utc)
    sync = session.get(MFNavHistorySync, scheme_code)
    if sync is not None:
        fetched = sync.fetched_at
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        if now - fetched < HISTORY_REFETCH_AFTER:
            return
    try:
        rows = nav_history.fetch_mfapi(scheme_code)
        nav_history.store_history(session, scheme_code, rows, now.date(), now)
    except Exception:  # noqa: BLE001 - never fail a run over a history fetch
        session.rollback()
        logger.warning("SIP NAV history fetch failed for scheme %s", scheme_code, exc_info=True)


def nav_for_due(session: Session, scheme_code: int, due: date) -> tuple[date, Decimal] | None:
    """(nav_date, nav) of the first NAV dated on or after `due`, or None when not published yet.

    Never falls back to the latest NAV for a past date (that is what nav_history.resolve_nav does,
    which is wrong for an instalment dated before the latest NAV).
    """
    latest = session.get(MFNavLatest, scheme_code)
    if latest is not None and latest.nav_date == due:
        return latest.nav_date, Decimal(str(latest.nav))
    found = _first_nav_on_or_after(session, scheme_code, due)
    sync = session.get(MFNavHistorySync, scheme_code)
    covered = sync is not None and sync.first_date is not None and sync.first_date <= due
    if found is not None and covered and found[0] - due <= MAX_NAV_GAP:
        return found
    ensure_history(session, scheme_code)
    found = _first_nav_on_or_after(session, scheme_code, due)
    if found is None:
        return None
    if found[0] - due <= MAX_NAV_GAP:
        return found
    # A NAV far after the due date means the history has a gap, not a holiday: wait for it to
    # fill. The exception is a due date older than the stored history, which can't improve.
    sync = session.get(MFNavHistorySync, scheme_code)
    if sync is not None and sync.first_date is not None and sync.first_date > due:
        return found
    return None


# --- Posting -------------------------------------------------------------------


def ensure_opening_transaction(session: Session, holding: MutualFund) -> MFTransaction | None:
    """Give a holding with no transactions an opening purchase of what it already was.

    Keeps XIRR on the transaction basis once an instalment or a sale is added. Returns the new
    transaction (added to the session, not flushed), or None when nothing was needed.
    """
    has_transactions = session.scalar(
        sa.select(sa.func.count())
        .select_from(MFTransaction)
        .where(MFTransaction.mutual_fund_id == holding.id)
    )
    if has_transactions or Decimal(str(holding.units)) <= 0:
        return None
    opening = MFTransaction(
        mutual_fund_id=holding.id,
        txn_date=holding.purchase_date,
        kind="purchase",
        amount=holding.invested_amount,
        units=holding.units,
    )
    session.add(opening)
    return opening


def _post_one(session: Session, sip: MfSip, today: date) -> int:
    """Post every due, unskipped instalment of one SIP (stops at the first missing NAV)."""
    holding = None
    if sip.mutual_fund_id is not None:
        holding = session.scalars(
            sa.select(MutualFund).where(
                MutualFund.id == sip.mutual_fund_id, MutualFund.user_id == sip.user_id
            )
        ).first()
        if holding is None:  # deleted (soft)
            return 0
    elif sip.last_posted_on is not None:
        return 0  # its holding was purged for good: don't quietly create a new one

    skipped = set(session.scalars(sa.select(MfSipSkip.due_date).where(MfSipSkip.sip_id == sip.id)))
    dues = due_dates(
        sip.day_of_month, sip.post_from, today, sip.end_date, skipped, sip.last_posted_on
    )
    if not dues:
        return 0

    if holding is not None:
        ensure_opening_transaction(session, holding)

    posted = 0
    for due in dues:
        found = nav_for_due(session, sip.scheme_code, due)
        if found is None:
            break
        nav_date, nav = found
        units = units_for(Decimal(str(sip.amount)), nav)
        amount = Decimal(str(sip.amount))
        if holding is None:
            master = session.get(MFMaster, sip.scheme_code)
            holding = MutualFund(
                user_id=sip.user_id,
                scheme_name=master.name[:200],
                scheme_code=sip.scheme_code,
                platform=sip.platform,
                category=master.category,
                units=Decimal("0"),
                avg_nav=Decimal("0"),
                invested_amount=Decimal("0"),
                purchase_date=nav_date,
            )
            session.add(holding)
            session.flush()
            sip.mutual_fund_id = holding.id
        session.add(
            MFTransaction(
                mutual_fund_id=holding.id,
                txn_date=nav_date,
                kind="purchase",
                amount=amount,
                units=units,
                sip_id=sip.id,
            )
        )
        total_units = Decimal(str(holding.units)) + units
        total_invested = Decimal(str(holding.invested_amount)) + amount
        holding.units = total_units
        holding.invested_amount = total_invested
        holding.avg_nav = (total_invested / total_units).quantize(NAV_DP, rounding=ROUND_HALF_UP)
        sip.last_posted_on = due
        posted += 1
    session.commit()
    return posted


def post_due(session: Session, today: date, sip_ids: list[int] | None = None) -> dict[int, int]:
    """Add every instalment due on or before `today`. Returns {sip_id: instalments added}.

    Idempotent (last_posted_on and the unique (sip_id, txn_date) key). Errors are logged per SIP
    and never raised.
    """
    statement = sa.select(MfSip.id).where(MfSip.status == ACTIVE, MfSip.post_from <= today)
    if sip_ids is not None:
        statement = statement.where(MfSip.id.in_(sip_ids))
    result: dict[int, int] = {}
    for sip_id in session.scalars(statement.order_by(MfSip.id)).all():
        try:
            sip = session.get(MfSip, sip_id)
            result[sip_id] = _post_one(session, sip, today) if sip is not None else 0
        except Exception:  # noqa: BLE001 - one SIP must not stop the others or the NAV import
            session.rollback()
            logger.warning("SIP %s posting failed", sip_id, exc_info=True)
            result[sip_id] = 0
    return result


def post_due_safely(session: Session) -> int:
    """Nightly hook: post what is due as of today (IST). Never raises. Returns instalments added."""
    try:
        return sum(post_due(session, today_ist()).values())
    except Exception:  # noqa: BLE001
        session.rollback()
        logger.warning("SIP posting run failed", exc_info=True)
        return 0


# --- Read helpers (used by the endpoints) -------------------------------------


def next_date_of(sip: MfSip, today: date) -> date | None:
    """The next instalment date of an active SIP; paused and stopped SIPs have none."""
    if sip.status != ACTIVE:
        return None
    return next_due(sip.day_of_month, today, sip.post_from, sip.end_date, sip.last_posted_on)


def instalment_stats(session: Session, sip_ids: list[int]) -> dict[int, tuple[int, Decimal]]:
    """{sip_id: (instalments added, amount invested through the SIP)}."""
    if not sip_ids:
        return {}
    rows = session.execute(
        sa.select(MFTransaction.sip_id, sa.func.count(), sa.func.sum(MFTransaction.amount))
        .where(MFTransaction.sip_id.in_(sip_ids))
        .group_by(MFTransaction.sip_id)
    ).all()
    return {r[0]: (r[1], Decimal(str(r[2] or 0))) for r in rows}


def upcoming_skips(session: Session, sip_ids: list[int], today: date) -> dict[int, list[date]]:
    """{sip_id: skipped instalment dates still ahead, oldest first}."""
    if not sip_ids:
        return {}
    rows = session.execute(
        sa.select(MfSipSkip.sip_id, MfSipSkip.due_date)
        .where(MfSipSkip.sip_id.in_(sip_ids), MfSipSkip.due_date >= today)
        .order_by(MfSipSkip.due_date)
    ).all()
    out: dict[int, list[date]] = {}
    for sip_id, due in rows:
        out.setdefault(sip_id, []).append(due)
    return out


def summaries_for_holdings(
    session: Session, holding_ids: list[int], today: date
) -> dict[int, dict[str, Any]]:
    """The SIP to show per MF holding (active before paused, newest first; stopped ones hidden).

    One query for any number of holdings.
    """
    if not holding_ids:
        return {}
    rows = session.scalars(
        sa.select(MfSip)
        .where(MfSip.mutual_fund_id.in_(holding_ids), MfSip.status.in_([ACTIVE, PAUSED]))
        .order_by(sa.case((MfSip.status == ACTIVE, 0), else_=1), MfSip.id.desc())
    ).all()
    out: dict[int, dict[str, Any]] = {}
    for sip in rows:
        if sip.mutual_fund_id in out:
            continue
        next_date = next_date_of(sip, today)
        out[sip.mutual_fund_id] = {
            "id": sip.id,
            "amount": float(sip.amount),
            "day_of_month": sip.day_of_month,
            "status": sip.status,
            "next_date": next_date.isoformat() if next_date else None,
        }
    return out

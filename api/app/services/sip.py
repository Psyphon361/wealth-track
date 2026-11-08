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


def nav_for_due(
    session: Session, scheme_code: int, due: date, fetch: bool = True
) -> tuple[date, Decimal] | None:
    """(nav_date, nav) of the first NAV dated on or after `due`, or None when not published yet.

    Never falls back to the latest NAV for a past date (that is what nav_history.resolve_nav does,
    which is wrong for an instalment dated before the latest NAV).

    `fetch=False` reads stored history only: no network, no commit, no rollback (used while
    row locks are held, since a commit would release them).
    """
    latest = session.get(MFNavLatest, scheme_code)
    if latest is not None and latest.nav_date == due:
        return latest.nav_date, Decimal(str(latest.nav))
    found = _first_nav_on_or_after(session, scheme_code, due)
    sync = session.get(MFNavHistorySync, scheme_code)
    covered = sync is not None and sync.first_date is not None and sync.first_date <= due
    if found is not None and covered and found[0] - due <= MAX_NAV_GAP:
        return found
    if fetch:
        ensure_history(session, scheme_code)
    found = _first_nav_on_or_after(session, scheme_code, due)
    if found is None:
        return None
    sync = session.get(MFNavHistorySync, scheme_code)
    older_than_history = sync is not None and sync.first_date is not None and sync.first_date > due
    covered = sync is not None and sync.first_date is not None and sync.first_date <= due
    if found[0] - due <= MAX_NAV_GAP:
        # Without a fetch, only trust stored history that covers the due date (or predates it
        # for good): a prefetch that failed or saw other dates must not post at a guessed NAV.
        if fetch or covered or older_than_history:
            return found
        return None
    # A NAV far after the due date means the history has a gap, not a holiday: wait for it to
    # fill. The exception is a due date older than the stored history, which can't improve.
    if older_than_history:
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
    if (
        has_transactions
        or Decimal(str(holding.units)) <= 0
        or Decimal(str(holding.invested_amount)) <= 0  # a transaction's amount must be positive
    ):
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


def _active_target(session: Session, sip: MfSip) -> MutualFund | None:
    """The one active holding of the SIP's fund and platform (locked), or None.

    Platform is compared ignoring case and spaces, as the create-time match does. With none or
    several matches the caller makes a new holding rather than guess or mix platforms.
    """
    matches = session.scalars(
        sa.select(MutualFund)
        .where(
            MutualFund.user_id == sip.user_id,
            MutualFund.scheme_code == sip.scheme_code,
            MutualFund.closed_on.is_(None),
            sa.func.lower(sa.func.trim(MutualFund.platform)) == sip.platform.strip().lower(),
        )
        .order_by(MutualFund.id)
        .with_for_update(of=MutualFund)
        .execution_options(populate_existing=True)
    ).all()
    return matches[0] if len(matches) == 1 else None


def _prefetch_history(session: Session, sip: MfSip, today: date) -> None:
    """Load NAV history for the SIP's due dates BEFORE any lock is taken.

    The history fetch commits (and rolls back on failure), which would release row locks and
    discard posted instalments, so it must never run inside the locked loop.
    """
    if sip.status != ACTIVE:
        return
    skipped = set(session.scalars(sa.select(MfSipSkip.due_date).where(MfSipSkip.sip_id == sip.id)))
    scheme_code = sip.scheme_code
    dues = due_dates(
        sip.day_of_month, sip.post_from, today, sip.end_date, skipped, sip.last_posted_on
    )
    for due in dues:
        if nav_for_due(session, scheme_code, due, fetch=True) is None:
            break
    session.commit()  # end the read transaction; nothing is locked yet


def _post_one(session: Session, sip: MfSip, today: date) -> int:
    """Post every due, unskipped instalment of one SIP (stops at the first missing NAV)."""
    sip_id = sip.id
    _prefetch_history(session, sip, today)
    sip = session.get(MfSip, sip_id)
    if sip is None:
        session.rollback()
        return 0
    holding = None
    linked_fund_id = sip.mutual_fund_id  # what the holding choice below is based on
    if sip.mutual_fund_id is not None:
        holding = session.scalars(
            sa.select(MutualFund).where(
                MutualFund.id == sip.mutual_fund_id, MutualFund.user_id == sip.user_id
            )
            .with_for_update(of=MutualFund)  # units and invested must be current (a sale may be in flight)
            .execution_options(populate_existing=True)
        ).first()
        # None here means soft-deleted (the soft-delete criteria hide the row; a deleted row is
        # never posted into and is left untouched).
    if holding is None or holding.closed_on is not None:
        # Missing (soft-deleted, or purged so mutual_fund_id is NULL) or sold: the SIP keeps
        # running. Move to the user's one active holding of the same fund and platform (locked,
        # like the fund above), or start a new one at the first instalment (holding stays None
        # until then).
        holding = _active_target(session, sip)

    # Re-read under lock (fund first, then SIP, like a sale): a concurrent full sale may have
    # stopped this SIP since the caller loaded it.
    sip = session.scalars(
        sa.select(MfSip)
        .where(MfSip.id == sip.id)
        .with_for_update(of=MfSip)
        .execution_options(populate_existing=True)
    ).first()
    if sip is None or sip.status != ACTIVE or sip.mutual_fund_id != linked_fund_id:
        # Stale, paused, stopped, or another run linked the SIP to a holding since the holding
        # choice above was made (it would otherwise start a second holding). Release the locks
        # (no network I/O may run while they are held); the next run picks it up.
        session.rollback()
        return 0

    skipped = set(session.scalars(sa.select(MfSipSkip.due_date).where(MfSipSkip.sip_id == sip.id)))
    dues = due_dates(
        sip.day_of_month, sip.post_from, today, sip.end_date, skipped, sip.last_posted_on
    )
    if not dues:
        session.rollback()
        return 0

    if holding is not None:
        sip.mutual_fund_id = holding.id  # no-op unless it moved off a sold holding
        ensure_opening_transaction(session, holding)

    posted = 0
    for due in dues:
        found = nav_for_due(session, sip.scheme_code, due, fetch=False)  # history loaded before locks
        if found is None:
            break
        nav_date, nav = found
        units = units_for(Decimal(str(sip.amount)), nav)
        amount = Decimal(str(sip.amount))
        new_holding = holding is None
        if holding is None:
            master = session.get(MFMaster, sip.scheme_code)
            # Built from the first instalment, so the row is valid (units > 0) when first flushed.
            holding = MutualFund(
                user_id=sip.user_id,
                scheme_name=master.name[:200],
                scheme_code=sip.scheme_code,
                platform=sip.platform,
                category=master.category,
                units=units,
                avg_nav=(amount / units).quantize(NAV_DP, rounding=ROUND_HALF_UP),
                invested_amount=amount,
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
        if not new_holding:
            total_units = Decimal(str(holding.units)) + units
            total_invested = Decimal(str(holding.invested_amount)) + amount
            holding.units = total_units
            holding.invested_amount = total_invested
            holding.avg_nav = (total_invested / total_units).quantize(
                NAV_DP, rounding=ROUND_HALF_UP
            )
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

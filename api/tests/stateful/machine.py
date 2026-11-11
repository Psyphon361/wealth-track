"""The money-conservation state machine (shared by the SQLite and the Postgres test).

The machine drives the HTTP API (assets, exits, SIPs) and keeps its OWN model of the world: the
expected balance of every cash account, and for every holding whether it is live, deleted or closed,
its quantity and invested amount, its exits and its fundings. The model is updated ONLY from
2xx responses. Every rule PREDICTS the outcome from the model and requires exactly that status
(or, where the model cannot know, a fixed small set), so a wrong 4xx fails as surely as a 5xx.

Cash semantics modelled (the "ideal" ledger): a cash account's balance is always
initial + exit proceeds paid into it - active fundings paid from it (reset by a PUT of the balance), whether
or not the account is soft-deleted. Deleting a holding refunds its funding, restoring it debits it again
(409 when short, also for a deleted account). A holding with a sale or settlement can't be deleted.
Editing the cost of a funded holding (rule edit_funded, SPEC §8c "Edit") moves the difference on the account
and gives the funding the new amount, unless the holding is out of sync with its funding (SIP posting, CAS),
the account was purged (both save, no money moves), the account is deleted, the increase is beyond the
balance or the cost would be zero (422).

Invariants after EVERY step: no 5xx; app balance == model balance for every cash account (live or
deleted); no negative cash; the exits and fundings in the database are exactly the model's; no
orphan exit or funding; a funding is active exactly while its holding is live; no double settlement;
a live fund's units equal its net transactions; no dangling SIP link; no purchase transaction
dated after a fund's closed_on; SIP posting never touches a closed or deleted fund; a partly sold
holding keeps invested >= remainder floor; sale costs of a fully sold holding sum to what was
invested; sell-then-undo restores quantity/units/weight, invested and closed_on exactly; GET then
PUT of the same body returns 200 (409 for a closed holding); the row-derived ledger formula
(initial + exits - fundings) as a secondary check.

Asset types: fd, rd, stock, bond, mf, nps, gold, pf, other (plus cash accounts) are added, edited, deleted, restored
and purged. Sell: stock, bond, mf, gold, other. Settle (matured only): fd, rd, bond. An RD's invested amount is its
monthly instalment times the instalments paid on the harness clock (it grows as days pass; the Paid From amount is
that figure at creation). Editing RD, NPS and EPF & PPF (rule edit_running) moves no money and leaves the funding as
it was; editing the cost of the other types moves the account (rule edit_funded). NPS needs the seeded scheme master
(world.py; NAV only after the market rule ran, else valued at contributed).

Purge and time: rules let days pass and run the purge (service or /api/cron/purge); deleted rows are
back-dated to the age the harness clock gives them. The model predicts the counts, that rows past 30
days go with their exits, fundings and MF transactions, that links to a purged cash account become
NULL, that no balance changes and that restore of a purged row is 404.

Buy more (rules buy_more, buy_more_twice, undo_buy, undo_buy_twice; SPEC §8d): a fund (also a partly sold one) gets
a manual purchase on a date from its purchase date and latest sale to today; units, invested and average NAV move
by the purchase, no cash account moves. 404 deleted, 409 sold in full, 422 for a future date, a date before the
purchase date or before the latest sale, 409 for the same buy again unless confirmed. Undo removes it again:
409 once the fund is sold in full, while a sale is dated on or after the buy (also right after a sell the same
day), or when the rest would leave no units or less than the cost floor; 404 for a record that is gone.

Known limits (documented, see test_money_machine.py): no concurrency (tests/pg covers it); SQLite
does not enforce foreign keys, so the harness applies the ON DELETE actions by hand after a purge
(Postgres enforces them for real).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, ROUND_UP, Decimal

import hypothesis.strategies as st
from hypothesis import event
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from tests.stateful.world import (
    LAST_TODAY, SCHEME, START_TODAY, Harness, d, from_cents, from_milli, q2, q3, rd_count, reason, sx,
)  # fmt: skip

SELLABLE = ("stock", "bond", "mf", "gold", "other")
SETTLEABLE = ("fd", "rd", "bond")  # SPEC §8b: a matured deposit or bond is settled; nps and pf have no exits
ADD_SLUGS = ("fd", "rd", "stock", "bond", "mf", "nps", "gold", "pf", "other")
ADJ_SLUGS = ("fd", "stock", "bond", "mf", "gold", "other")  # a cost edit moves money (SPEC §8c "Edit")
RUNNING_SLUGS = ("rd", "nps", "pf")  # a cost edit moves NO money and the funding keeps its amount
TABLES = {
    "fd": "fixed_deposits", "rd": "recurring_deposits", "stock": "stocks", "bond": "bonds",
    "mf": "mutual_funds", "nps": "nps_holdings", "gold": "gold_holdings", "pf": "pf_holdings",
    "other": "other_holdings", "cash": "cash_holdings",
}  # fmt: skip
ZERO = Decimal("0")
CENT = Decimal("0.01")
TOO_MUCH = "More than this account's balance"
REFUSED = "Can't sell part of this holding"


# --- the model ---------------------------------------------------------------------------------


@dataclass
class CashM:
    id: int
    name: str
    kind: str
    bal: Decimal
    initial: Decimal
    live: bool = True
    put: bool = False
    del_day: date | None = None  # the harness day it was soft-deleted (None while live)


@dataclass
class FundM:
    cash_id: int | None  # None once the account was purged (the link is set to NULL)
    amount: Decimal
    from_exit: int | None
    active: bool = True


@dataclass
class HM:
    slug: str
    id: int
    qty: Decimal | None  # shares, bond units, fund units, grams; None for fd and other
    invested: Decimal | None  # None: derived (stock) or unset (other)
    start: date | None
    price: Decimal | None = None  # stock average price
    matured: bool = False  # fd/bond: past maturity (can be settled, a bond can't be sold)
    platform: str = ""
    master_id: int | None = None  # stock: the stock master it is linked to (a price can apply)
    metal: str = "gold"  # gold holdings: gold or silver
    live: bool = True
    del_day: date | None = None  # the harness day it was soft-deleted (None while live)
    closed: bool = False  # sold in full (closed_on set)
    settled: bool = False
    cost_edited: bool = False  # a PUT changed the cost: a fund's cost no longer equals its transactions
    invested0: Decimal = ZERO
    monthly: Decimal | None = None  # rd: the monthly instalment
    months: int = 0  # rd: tenure in months (the number of instalments a full term pays)
    bal: Decimal | None = None  # pf: balance, interest rate and balance date (invested = contributed or current)
    rate: Decimal | None = None
    bdate: date | None = None
    exits: list[int] = field(default_factory=list)
    fundings: list[FundM] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, int]:
        return (self.slug, self.id)

    def inv(self) -> Decimal | None:
        if self.slug == "stock":
            return q2(self.qty * self.price)
        return self.invested


@dataclass
class ExitM:
    id: int
    slug: str
    hid: int
    kind: str  # sale | maturity
    cash_id: int | None
    added: Decimal  # money paid into the account (0 when none)
    amount: Decimal
    qty: Decimal | None
    full: bool
    pre: tuple | None = None  # (qty, invested, closed) before the sale
    post: tuple | None = None  # the same right after it


@dataclass
class BuyM:
    """A manual purchase added with Buy more (a manual mf_transactions row)."""

    id: int  # the transaction id
    hid: int  # the fund
    when: date
    amount: Decimal
    units: Decimal


@dataclass
class SipM:
    id: int
    status: str = "active"  # active | paused | stopped
    amount: int = 0
    day: int = 0


class Fail(AssertionError):
    pass


# Counts of valid steps and legal rejections (hypothesis' own statistics are not printed for
# run_state_machine_as_test); the test reads and asserts on it.
TALLY: Counter = Counter()
# Observed over 40 random seeds: the share of valid steps varies between 64% and ~80%, so 70% failed
# on luck. 55% still catches strategies that have gone wild.
MIN_VALID_SHARE = 0.55
RETENTION_DAYS = 30  # SPEC §4: deleted holdings are kept for 30 days (the purge removes "more than 30")


def _years_from_today(years: int) -> date:
    """The machine's first day plus whole years (fixed, not the wall clock)."""
    return date(START_TODAY.year + years, START_TODAY.month, min(START_TODAY.day, 28))


def report_and_check_valid_share(label: str) -> None:
    total = TALLY["valid"] + TALLY["rejected"]
    share = TALLY["valid"] / total if total else 0
    lines = sorted(f"  {key}: {n}" for key, n in TALLY.items() if key not in ("valid", "rejected"))
    print(f"\n[{label}] steps with a response: {total}, valid {share:.0%}\n" + "\n".join(lines))
    assert share >= MIN_VALID_SHARE, f"only {share:.0%} of the steps were valid (the strategies are too wild)"


def floor_of(slug: str, left: Decimal) -> Decimal:
    if slug == "mf":
        return max((Decimal("0.00005") * left).quantize(CENT, rounding=ROUND_UP), CENT)
    return CENT


# --- the machine --------------------------------------------------------------------------------


class MoneyMachine(RuleBasedStateMachine):
    def __init__(self, harness: Harness) -> None:
        super().__init__()
        self.h = harness
        harness.reset()  # also asserts the engine is a test database
        self.cash: dict[int, CashM] = {}
        self.holds: dict[tuple[str, int], HM] = {}
        self.exits: dict[int, ExitM] = {}
        self.gone: list[int] = []  # exit ids that were undone
        self.sips: dict[int, SipM] = {}
        self.buys: dict[int, BuyM] = {}  # manual purchases (Buy more) still on record, by transaction id
        self.touched: tuple[str, int] | None = None
        self.n = 0
        self.rate_dates: dict[tuple[str, str], date] = {}  # latest rate date per metal (never goes back)
        self.steps = 0  # invariant runs, for the read oracle's cadence
        self.u2cash: dict[int, Decimal] = {}  # the second user's cash accounts: id -> balance
        self.u2hold: list[tuple[str, int, Decimal, Decimal | None]] = []  # (slug, id, invested, quantity)

    # ---- plumbing ---------------------------------------------------------------------------
    def fail(self, message: str):
        raise Fail(f"{message}\n{self.h.tail()}")

    def expect(self, r, allowed: tuple[int, ...], what: str, prefix: str | None = None) -> int:
        if r.status_code not in allowed:
            self.fail(f"{what}: expected {allowed}, got {r.status_code}: {r.text[:400]}")
        if prefix is not None and r.status_code >= 400:
            text = reason(r)
            if not text.startswith(prefix):
                self.fail(f"{what}: expected a message starting {prefix!r}, got {text!r}")
        event("step valid" if r.status_code < 300 else "step legal rejection")
        event(f"{what} {r.status_code}")
        if " again" in what or what.startswith("cross-user"):
            TALLY["refusals on purpose (repeats, other user's ids)"] += 1  # not part of the valid share
        else:
            TALLY["valid" if r.status_code < 300 else "rejected"] += 1
        TALLY[f"{what} {r.status_code}"] += 1
        return r.status_code

    def name(self, stem: str) -> str:
        self.n += 1
        return f"{stem} {self.n}"

    def live_cash(self) -> list[CashM]:
        return sorted((c for c in self.cash.values() if c.live), key=lambda c: c.id)

    def dead_cash(self) -> list[CashM]:
        return sorted((c for c in self.cash.values() if not c.live), key=lambda c: c.id)

    def holds_of(self, *slugs: str, live: bool | None = None) -> list[HM]:
        found = [h for h in self.holds.values() if h.slug in slugs and (live is None or h.live == live)]
        return sorted(found, key=lambda h: h.key)

    # ---- reading the app ----------------------------------------------------------------------
    def refresh_mf(self) -> None:
        """MF units/invested change by SIP posting: read them (and register funds a SIP created)."""
        for r in self.h.rows(
            "SELECT id, units, invested_amount, closed_on, deleted_at, platform FROM mutual_funds "
            "WHERE user_id = :u", u=self.h.uid,
        ):  # fmt: skip
            hold = self.holds.get(("mf", r.id))
            if hold is None:  # a fund a SIP created: live/closed come from the app only here
                hold = HM("mf", r.id, q3(r.units), q2(r.invested_amount), None, platform=r.platform or "")
                hold.invested0 = hold.invested
                hold.live, hold.closed = r.deleted_at is None, r.closed_on is not None
                self.holds[hold.key] = hold
            hold.qty, hold.invested = q3(r.units), q2(r.invested_amount)

    def db_state(self, hold: HM) -> tuple:
        """(qty, invested, closed) of a holding as the database has it."""
        table = TABLES[hold.slug]
        cols = {
            "stock": "quantity, NULL, closed_on", "bond": "quantity, invested_amount, closed_on",
            "gold": "weight_grams, invested_amount, closed_on", "other": "NULL, invested_amount, closed_on",
            "mf": "units, invested_amount, closed_on",
        }[hold.slug]  # fmt: skip
        rows = self.h.rows(f"SELECT {cols} FROM {table} WHERE id = :i", i=hold.id)  # noqa: S608
        qty, invested, closed_on = rows[0]
        if qty is not None:
            qty = d(qty) if hold.slug in ("stock", "bond") else q3(qty)
        return (qty, None if invested is None else q2(invested), closed_on is not None)

    def frozen(self) -> dict[int, tuple]:
        """Closed or deleted funds as the database has them: SIP posting must not change them."""
        out = {}
        for r in self.h.rows(
            "SELECT id, units, invested_amount FROM mutual_funds "
            "WHERE user_id = :u AND (closed_on IS NOT NULL OR deleted_at IS NOT NULL)", u=self.h.uid,
        ):  # fmt: skip
            count = self.h.scalar("SELECT count(*) FROM mf_transactions WHERE mutual_fund_id = :i", i=r.id)
            out[r.id] = (q3(r.units), q2(r.invested_amount), count)
        return out

    # ---- strategies for bodies ----------------------------------------------------------------
    def build(self, data, slug: str, forced: int | None = None):
        """(request body, HM template, amount a Paid From would take or None)."""
        draw = data.draw
        if slug == "fd":
            matured = draw(st.sampled_from([True, True, True, False]))
            cents = forced or draw(st.integers(100, 2_000_000))
            body = {
                "bank": self.name("Bank"), "principal": sx(from_cents(cents)), "rate": 7,
                # not matured: starts 30 days before the machine's first day and runs 5 years, so
                # it is never matured however far the (frozen) calendar moves
                "start_date": "2023-01-01" if matured else (START_TODAY - timedelta(days=30)).isoformat(),
                "compounding": "quarterly",
                "payout_type": "cumulative", "tenure_years": 1 if matured else 5,
            }  # fmt: skip
            hold = HM("fd", 0, None, None, None, matured=matured)
            hold.invested0 = from_cents(cents)  # the principal (what the read oracle expects)
            return body, hold, from_cents(cents)
        if slug == "stock":
            qty = 1 if forced else draw(st.integers(1, 60))
            cents = forced or draw(st.integers(100, 300_000))
            body = {
                "name": self.name("Stock"), "exchange": "NSE", "quantity": qty,
                "avg_buy_price": sx(from_cents(cents)), "buy_date": "2025-01-01",
            }  # fmt: skip
            master = draw(st.sampled_from([None, *self.h.stock_masters]))
            if master is not None:  # linked: the market rule's price applies (the name comes from the master)
                body["master_id"] = master
            hold = HM("stock", 0, Decimal(qty), None, date(2025, 1, 1), price=from_cents(cents), master_id=master)
            hold.invested0 = q2(hold.qty * hold.price)
            return body, hold, hold.invested0
        if slug == "bond":
            matured = draw(st.sampled_from([True, False, False]))
            qty = 1 if forced else draw(st.integers(1, 40))
            cents = forced or draw(st.integers(100, 200_000))
            price = from_cents(cents)
            invested = q2(qty * price)
            body = {
                "name": self.name("Bond"), "issuer": "Issuer", "bond_type": "corporate",
                "quantity": qty, "face_value": 1000, "purchase_price": sx(price),
                "invested_amount": sx(invested), "ytm": 8,
                "purchase_date": "2022-01-01" if matured else "2025-01-01",
                # not matured: 5 years after the machine's first day
                "maturity_date": "2024-01-01" if matured else _years_from_today(5).isoformat(),
            }  # fmt: skip
            hold = HM("bond", 0, Decimal(qty), invested, date(2022, 1, 1) if matured else date(2025, 1, 1),
                      matured=matured)  # fmt: skip
            hold.invested0 = invested
            return body, hold, invested
        if slug == "mf":
            milli = 1000 if forced else draw(st.integers(1_000, 300_000))
            nav_cents = forced or draw(st.integers(1_000, 30_000))
            units, nav = from_milli(milli), from_cents(nav_cents)
            invested = q2(units * nav)
            platform = draw(st.sampled_from(["Groww", "Zerodha"]))
            body = {
                "scheme_name": "Fund A", "scheme_code": SCHEME, "platform": platform,
                "category": "equity", "units": sx(units), "avg_nav": sx(nav),
                "invested_amount": sx(invested), "purchase_date": "2025-06-01",
            }  # fmt: skip
            hold = HM("mf", 0, units, invested, date(2025, 6, 1), platform=platform)
            hold.invested0 = invested
            return body, hold, invested
        if slug == "gold":
            milli = draw(st.integers(1_000, 100_000))
            cents = forced or draw(st.integers(10_000, 5_000_000))
            invested = from_cents(cents)
            metal = draw(st.sampled_from(["gold", "gold", "silver"]))
            body = {
                "name": self.name("Gold"), "form": "coin", "metal": metal, "purity": "999",
                "weight_grams": sx(from_milli(milli)), "purchase_date": "2025-01-01",
                "invested_amount": sx(invested),
            }  # fmt: skip
            hold = HM("gold", 0, from_milli(milli), invested, date(2025, 1, 1), metal=metal)
            hold.invested0 = invested
            return body, hold, invested
        if slug == "rd":
            today = self.h.today
            # (start, tenure years, tenure months, matured): the matured ones ended long before the machine's
            # clock; the others run for years, from a month ago or from this day of the month
            start, years, months, matured = draw(st.sampled_from([
                (date(2023, 1, 1), 1, 0, True), (date(2025, 1, 1), 0, 6, True),
                (START_TODAY - timedelta(days=30), 5, 0, False),
                (START_TODAY - timedelta(days=30), 5, 0, False),
                (date(today.year, today.month, min(today.day, 28)), 5, 0, False),
            ]))  # fmt: skip
            total = years * 12 + months
            count = rd_count(start, total, today)
            if forced and forced % count == 0:
                cents = forced // count  # exactly the balance (or one cent over): the edge cases
            elif forced:
                cents = draw(st.integers(1, max(1, forced // count)))
            else:
                cents = draw(st.integers(100, 50_000))
            monthly = from_cents(cents)
            body = {
                "bank": self.name("RD Bank"), "monthly_instalment": sx(monthly), "rate": 7,
                "start_date": start.isoformat(), "compounding": "quarterly",
                "tenure_years": years, "tenure_months": months,
            }  # fmt: skip
            hold = HM("rd", 0, None, None, start, matured=matured, monthly=monthly, months=total)
            return body, hold, q2(monthly * count)
        if slug == "nps":
            units = from_cents(draw(st.integers(1_000, 500_000))).scaleb(-2)  # 4 dp: 0.1 .. 500
            cents = forced or draw(st.integers(100, 3_000_000))
            # a start date no other holding has: two holdings of one scheme and day are a duplicate warning
            start = date(2015, 1, 1) + timedelta(days=self.n + 1)
            self.name("NPS")
            body = {
                "scheme_id": draw(st.sampled_from(self.h.nps_schemes)), "units": sx(units),
                "contributed": sx(from_cents(cents)), "start_date": start.isoformat(),
            }  # fmt: skip
            hold = HM("nps", 0, units, from_cents(cents), start)
            hold.invested0 = from_cents(cents)
            return body, hold, from_cents(cents)
        if slug == "pf":
            kind = draw(st.sampled_from(["epf", "vpf", "ppf"]))
            has_contributed = draw(st.sampled_from([True, True, False]))
            balance_cents = draw(st.integers(100, 5_000_000))
            contributed_cents = draw(st.integers(100, 3_000_000))
            if forced and has_contributed:
                contributed_cents = forced
            elif forced:
                balance_cents = forced
            rate = Decimal(draw(st.sampled_from(["7.1", "8.25", "8.15"])))
            body = {
                "name": self.name("PF"), "kind": kind, "balance": sx(from_cents(balance_cents)),
                "balance_date": "2026-01-01", "interest_rate": sx(rate),
                "contributed": sx(from_cents(contributed_cents)) if has_contributed else None,
                "opened_on": draw(st.sampled_from(["2005-04-01", "2015-04-01"])) if kind == "ppf" else None,
            }  # fmt: skip
            contributed = from_cents(contributed_cents) if has_contributed else None
            hold = HM("pf", 0, None, contributed, date(2026, 1, 1), bal=from_cents(balance_cents), rate=rate,
                      bdate=date(2026, 1, 1))  # fmt: skip
            hold.invested0 = contributed or ZERO
            return body, hold, contributed if contributed is not None else from_cents(balance_cents)
        # other
        has_invested = bool(forced) or draw(st.sampled_from([True, True, True, False]))
        cents = forced or draw(st.integers(100, 5_000_000))
        acquired = draw(st.sampled_from(["2024-01-01", None]))
        body = {
            "name": self.name("Plot"), "category": "Property", "current_value": 80000,
            "value_date": "2026-01-01",
            "invested_amount": sx(from_cents(cents)) if has_invested else None,
            "acquired_on": acquired,
        }  # fmt: skip
        invested = from_cents(cents) if has_invested else None
        hold = HM("other", 0, None, invested, date(2024, 1, 1) if acquired else None)
        hold.invested0 = invested or ZERO
        return body, hold, invested

    # ---- create (add / reinvest) ------------------------------------------------------------
    def create(self, slug, body, hold, amount, cash: CashM | None, from_exit=None, confirm=True):
        """POST a create and update the model. Returns (status, request payload). With confirm=False
        the duplicate check runs: the callers only use names no holding has, so it must find nothing."""
        paid = None
        if cash is not None:
            paid = {"cash_id": cash.id}
            if from_exit is not None:
                paid["from_exit_id"] = from_exit
        payload = {**body, **({"paid_from": paid} if paid else {})}
        r = self.h.call(
            "POST", f"/api/assets/{slug}", params={"confirm_duplicate": "true"} if confirm else None, json=payload
        )  # fmt: skip
        prefix = None
        if cash is None:
            want = 201
        elif from_exit is not None and from_exit not in self.exits:
            want = 422
        elif not cash.live:
            want = 422
        elif amount is None:
            want = 422
        elif amount > cash.bal:
            want, prefix = 422, TOO_MUCH
        else:
            want = 201
        what = f"add {slug}" + (" paid" if cash else "")
        status = self.expect(r, (want,), what, prefix)
        if status >= 400:
            return status, payload
        hold.id = r.json()["id"]
        self.holds[hold.key] = hold
        if cash is not None:
            cash.bal -= amount
            hold.fundings.append(FundM(cash.id, amount, from_exit))
        self.touched = hold.key
        return status, payload

    @precondition(lambda self: len(self.cash) < 4)
    @rule(data=st.data())
    def add_cash(self, data):
        cents = data.draw(st.one_of(st.just(0), st.integers(0, 3_000_000)))
        kind = data.draw(st.sampled_from(["savings", "current", "cash"]))
        body = {
            "name": self.name("Acct"), "kind": kind, "balance": sx(from_cents(cents)),
            "balance_date": "2026-01-01",
        }  # fmt: skip
        r = self.h.call("POST", "/api/assets/cash", params={"confirm_duplicate": "true"}, json=body)
        self.expect(r, (201,), "add cash")
        cid = r.json()["id"]
        self.cash[cid] = CashM(cid, body["name"], kind, from_cents(cents), from_cents(cents))

    @rule(data=st.data())
    def add_holding(self, data):
        mode = data.draw(st.sampled_from(["none", "paid", "paid", "paid", "paid", "edge", "dead"]))
        # paid adds lean on NPS (its amount rule is the contributed value) so a wrong amount shows within a ci run
        slug = data.draw(st.sampled_from(ADD_SLUGS + (("nps", "nps", "pf") if mode in ("paid", "edge") else ())))
        pool = self.dead_cash() if mode == "dead" else self.live_cash()
        cash = data.draw(st.sampled_from(pool)) if pool and mode != "none" else None
        forced = None
        if cash is not None and mode in ("paid", "edge"):
            bal = int(cash.bal * 100)
            if mode == "edge" and bal > 0:
                forced = data.draw(st.sampled_from([bal, bal + 1]))
            elif bal > 0:
                forced = data.draw(st.integers(1, bal)) if slug in ("nps", "pf") or data.draw(st.booleans()) else None
        body, hold, amount = self.build(data, slug, forced)
        self.create(slug, body, hold, amount, cash)

    @precondition(lambda self: bool(self.exits))
    @rule(data=st.data())
    def reinvest(self, data):
        ex = self.exits[data.draw(st.sampled_from(sorted(self.exits)))]
        pool = self.live_cash()
        if not pool:
            return
        own = self.cash.get(ex.cash_id) if ex.cash_id is not None else None
        cash = own if own is not None and own.live else data.draw(st.sampled_from(pool))
        slug = data.draw(st.sampled_from(ADD_SLUGS))
        bal = int(cash.bal * 100)
        forced = data.draw(st.integers(1, bal)) if bal > 0 and data.draw(st.booleans()) else None
        body, hold, amount = self.build(data, slug, forced)
        stale = data.draw(st.sampled_from([False] * 9 + [True])) and self.gone
        self.create(slug, body, hold, amount, cash, from_exit=self.gone[-1] if stale else ex.id)

    # ---- cash balance -------------------------------------------------------------------------
    @precondition(lambda self: bool(self.live_cash()))
    @rule(data=st.data())
    def put_cash(self, data):
        c = data.draw(st.sampled_from(self.live_cash()))
        cents = data.draw(st.one_of(st.just(0), st.integers(0, 3_000_000)))
        body = {
            "name": c.name, "kind": c.kind, "balance": sx(from_cents(cents)),
            "balance_date": "2026-01-01",
        }  # fmt: skip
        r = self.h.call("PUT", f"/api/assets/cash/{c.id}", json=body)
        if self.expect(r, (200,), "put cash") < 400:
            c.bal, c.put = from_cents(cents), True

    # ---- edit the cost of a holding (SPEC §8c "Edit") -----------------------------------------
    @staticmethod
    def cost_now(hold: HM) -> Decimal | None:
        """The cost the app has stored for a holding (what Paid From took when it was in sync)."""
        if hold.slug == "fd":
            return hold.invested0
        if hold.slug == "stock":
            return hold.inv()
        return hold.invested

    @staticmethod
    def with_cost(slug: str, body: dict, cost: Decimal) -> tuple[dict, Decimal]:
        """`body` with its cost set near `cost`; returns (new body, the cost that body stands for)."""
        body = dict(body)
        if slug in ("stock", "bond"):
            qty = Decimal(str(body["quantity"]))
            cents = max(1, int((cost / qty * 100).to_integral_value(ROUND_HALF_UP)))
            price = from_cents(cents)
            cost = q2(qty * price)
            if slug == "stock":
                body["avg_buy_price"] = sx(price)
            else:
                body["purchase_price"], body["invested_amount"] = sx(price), sx(cost)
        elif slug == "fd":
            body["principal"] = sx(cost)
        elif slug == "mf":
            units = Decimal(str(body["units"]))
            cost = max(cost, q2(units * Decimal("0.01")) + CENT)
            body["avg_nav"] = sx((cost / units).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
            body["invested_amount"] = sx(cost)
        else:  # gold, other
            body["invested_amount"] = sx(cost)
        return body, cost

    @precondition(lambda self: bool(self.holds_of(*ADJ_SLUGS)))
    @rule(data=st.data())
    def edit_funded(self, data):
        """PUT a new cost for a holding (mostly one bought with Paid From): SPEC §8c "Edit". The model applies
        the rules in the app's order: closed 409, sold-in-part 422, unchanged cost nothing, no funding saves,
        a cost to zero 422, a holding out of sync with its funding (SIP posting, CAS) saves and moves nothing,
        a purged account saves and moves nothing, a deleted account 422, an increase beyond the balance 422,
        else the account moves by the difference and the funding takes the new amount (later deletes, restores,
        sales and undos use it)."""
        from app.routers.assets import REGISTRY
        from app.schemas.assets import SOLD_IN_PART_ERROR
        from app.schemas.fundings import (
            PAID_FROM_EDIT_DELETED_ERROR,
            PAID_FROM_EDIT_GONE_NOTE,
            PAID_FROM_EDIT_NOT_IN_SYNC_NOTE,
            PAID_FROM_EDIT_TOO_MUCH_ERROR,
            PAID_FROM_EDIT_ZERO_ERROR,
        )
        from app.services.sip import format_inr

        self.refresh_mf()  # SIP posting changes a fund's cost behind the funding's back
        open_funded = [
            h for h in self.holds_of(*ADJ_SLUGS, live=True)
            if any(f.active for f in h.fundings) and not h.closed and not h.settled
        ]  # fmt: skip
        hold = self.choose(data, open_funded, self.holds_of(*ADJ_SLUGS))
        slug = hold.slug
        funding = next((f for f in hold.fundings if f.active), None) if hold.live else None
        cash = self.cash.get(funding.cash_id) if funding and funding.cash_id is not None else None
        old = self.cost_now(hold)
        original = None
        if hold.live:
            got = self.h.call("GET", f"/api/assets/{slug}/{hold.id}")
            if got.status_code != 200:
                self.fail(f"edit {slug}: GET -> {got.status_code}")
            fields = REGISTRY[slug][1].model_fields
            original = {k: v for k, v in got.json().items() if k in fields}
        else:
            original = self.build(data, slug)[0]  # any valid body: a deleted holding is 404
        variant = data.draw(st.sampled_from(["down", "down", "up_fit", "up_fit", "up_over", "random", "same", "zero"]))
        base = funding.amount if funding else (old or Decimal(1000))
        body, new = dict(original), old
        if variant == "same":
            body["notes"] = "edited"
        elif variant == "zero" and slug == "other":
            body["invested_amount"], new = None, None
        else:
            if variant == "down":
                low = int(base * 100) - 1
                target = from_cents(data.draw(st.integers(100, max(100, low))))
            elif variant == "up_fit":
                room = int(cash.bal * 100) if cash is not None else 100_000
                target = base + from_cents(data.draw(st.integers(1, max(1, room))))
            elif variant == "up_over":
                extra = cash.bal if cash is not None else ZERO
                target = base + extra + from_cents(data.draw(st.integers(1, 100_000)))
            else:
                target = from_cents(data.draw(st.integers(100, 2_000_000)))
            body, new = self.with_cost(slug, original, target)
            if new == old:
                body = dict(original)  # nothing changes: not a single protected field is touched
        changed = new != old
        sale_on_record = any(self.exits[e].kind == "sale" for e in hold.exits)

        # prediction, in the order the app checks ------------------------------------------------
        prefix = None
        note = line = None
        if not hold.live:
            want = 404
        elif hold.closed or hold.settled:
            want = 409
        elif changed and sale_on_record:
            want, prefix = 422, SOLD_IN_PART_ERROR
        else:
            want = 200
            if not changed or funding is None:
                TALLY["edit funded: no funding or cost unchanged"] += 1
            elif new is None or new <= 0:
                want, prefix = 422, PAID_FROM_EDIT_ZERO_ERROR
                TALLY["edit funded: zero refused"] += 1
            elif old is None or q2(old) != funding.amount:
                name = cash.name if cash is not None else "its account"
                note = PAID_FROM_EDIT_NOT_IN_SYNC_NOTE.format(account=name)
                TALLY["edit funded: saved out of sync"] += 1
            elif funding.cash_id is None:
                note = PAID_FROM_EDIT_GONE_NOTE
                TALLY["edit funded: saved purged"] += 1
            elif not cash.live:
                want, prefix = 422, PAID_FROM_EDIT_DELETED_ERROR.split("{")[0]
                TALLY["edit funded: refused deleted account"] += 1
            elif new - funding.amount > cash.bal:
                want, prefix = 422, PAID_FROM_EDIT_TOO_MUCH_ERROR.split("{")[0]
                TALLY["edit funded: refused short"] += 1
            else:
                delta = new - funding.amount
                line = f"{cash.name}: {format_inr(cash.bal)} → {format_inr(cash.bal - delta)}"
                TALLY["edit funded: moved " + ("up" if delta > 0 else "down" if delta < 0 else "none")] += 1
                if funding.from_exit is not None:
                    TALLY["edit funded: moved on a reinvest funding"] += 1

        r = self.h.call("PUT", f"/api/assets/{slug}/{hold.id}", json=body)
        if self.expect(r, (want,), f"edit {slug}", prefix) >= 400:
            return
        text = r.json().get("description") or ""
        for extra in (line, note):
            if extra is not None and not text.endswith(" · " + extra):
                self.fail(f"edit {slug}: description {text!r} lacks {extra!r}")
        if line is None and note is None and " · " in text:
            self.fail(f"edit {slug}: description {text!r} has a note, none expected")
        if line is not None:
            cash.bal -= new - funding.amount
            funding.amount = new
        if changed:
            hold.cost_edited = True
            if slug == "fd":
                hold.invested0 = new
            elif slug == "stock":
                hold.price = Decimal(body["avg_buy_price"])
                hold.invested0 = hold.inv()
            else:
                hold.invested = new
                hold.invested0 = new if new is not None else ZERO
        self.touched = hold.key

    @precondition(lambda self: bool(self.holds_of(*RUNNING_SLUGS)))
    @rule(data=st.data())
    def edit_running(self, data):
        """PUT new values for an RD, NPS or EPF/PPF holding (SPEC §8c "Edit": their amount is a running figure, so
        an edit moves NO money, takes no funding lock and leaves the funding as it was, also when the new cost
        no longer matches what was paid; the description carries no account note). 404 when deleted, 409 once an
        RD is settled (RD, NPS and PF have no partial sales, so no sold-in-part guard). The invariants then check
        that no balance moved and every funding is the model's."""
        from app.routers.assets import REGISTRY

        open_ = [h for h in self.holds_of(*RUNNING_SLUGS, live=True) if not h.settled]
        paid = [h for h in open_ if any(f.active for f in h.fundings)]  # the ones that matter most: Paid From
        hold = self.choose(data, paid if paid and data.draw(st.booleans()) else open_, self.holds_of(*RUNNING_SLUGS))
        slug = hold.slug
        if hold.live:
            got = self.h.call("GET", f"/api/assets/{slug}/{hold.id}")
            if got.status_code != 200:
                self.fail(f"edit {slug}: GET -> {got.status_code}")
            fields = REGISTRY[slug][1].model_fields
            body = {k: v for k, v in got.json().items() if k in fields}
        else:
            body = self.build(data, slug)[0]  # any valid body: a deleted holding is 404
        new: dict = {}
        if data.draw(st.sampled_from(["change", "change", "change", "same"])) == "same":
            body["notes"] = "edited"
        elif slug == "rd":
            new["monthly"] = from_cents(data.draw(st.integers(100, 200_000)))
            body["monthly_instalment"] = sx(new["monthly"])
            body["rate"] = data.draw(st.sampled_from([6, 7, 9]))
        elif slug == "nps":
            new["units"] = from_cents(data.draw(st.integers(1_000, 500_000))).scaleb(-2)
            new["invested"] = from_cents(data.draw(st.integers(100, 3_000_000)))
            body["units"], body["contributed"] = sx(new["units"]), sx(new["invested"])
        else:  # pf
            new["bal"] = from_cents(data.draw(st.integers(100, 5_000_000)))
            new["invested"] = from_cents(data.draw(st.integers(100, 3_000_000))) if data.draw(st.booleans()) else None
            new["rate"] = Decimal(data.draw(st.sampled_from(["7.1", "8.25", "8.15"])))
            body["balance"], body["interest_rate"] = sx(new["bal"]), sx(new["rate"])
            body["contributed"] = sx(new["invested"]) if new["invested"] is not None else None
        want = 404 if not hold.live else 409 if hold.settled else 200
        funded = any(f.active for f in hold.fundings)
        r = self.h.call("PUT", f"/api/assets/{slug}/{hold.id}", json=body)
        if self.expect(r, (want,), f"edit running {slug}") >= 400:
            return
        if " · " in (r.json().get("description") or ""):
            self.fail(f"edit {slug}: description {r.json().get('description')!r} has an account note, none expected")
        if "monthly" in new:
            hold.monthly = new["monthly"]
        if "units" in new:
            hold.qty = new["units"]
        if "invested" in new:
            hold.invested = new["invested"]
            hold.invested0 = new["invested"] or ZERO
        if slug == "pf" and new:
            hold.bal, hold.rate = new["bal"], new["rate"]
        TALLY[f"edit running {slug}: {'changed' if new else 'unchanged'}{', paid from an account' if funded else ''}"] += 1
        self.touched = hold.key

    @precondition(lambda self: bool(self.live_cash() or self.holds_of("nps", "pf", "other")))
    @rule(data=st.data())
    def update_value(self, data):
        """POST update-value for a cash account, NPS, EPF/PPF or Other holding (the quick refresh): only the
        figure and its date change, no money moves and no funding changes (the invariants check both). 404 when
        deleted, 409 for an Other that was sold in full. A missing date means the harness day. The Other
        value stays 80000 (the oracle's constant); only its date moves."""
        picks = [("cash", c) for c in self.live_cash()] + [("hold", h) for h in self.holds_of("nps", "pf", "other")]
        kind, target = data.draw(st.sampled_from(picks))
        date_text = data.draw(st.sampled_from(["2026-02-01", None]))
        when = date.fromisoformat(date_text) if date_text else self.h.today
        if kind == "cash":
            slug, hid, live, want = "cash", target.id, True, 200
            cents = data.draw(st.one_of(st.just(0), st.integers(0, 3_000_000)))
            body = {"balance": sx(from_cents(cents))}
        else:
            slug, hid, live = target.slug, target.id, target.live
            want = 404 if not live else 409 if target.closed else 200
            if slug == "nps":
                units = from_cents(data.draw(st.integers(1_000, 500_000))).scaleb(-2)
                invested = from_cents(data.draw(st.integers(100, 3_000_000)))
                body = {"units": sx(units), "contributed": sx(invested)}
            elif slug == "pf":
                balance = from_cents(data.draw(st.integers(100, 5_000_000)))
                body = {"balance": sx(balance)}
            else:
                body = {"current_value": 80000}
        if slug != "nps" and date_text:
            body["balance_date" if slug in ("cash", "pf") else "value_date"] = date_text
        r = self.h.call("POST", f"/api/assets/{slug}/{hid}/update-value", json=body)
        if self.expect(r, (want,), f"update value {slug}") >= 400:
            return
        if kind == "cash":
            target.bal, target.put = from_cents(cents), True
        elif slug == "nps":
            target.qty, target.invested, target.invested0 = units, invested, invested
        elif slug == "pf":
            target.bal, target.bdate = balance, when
        TALLY[f"update value {slug}: {'dated' if date_text else 'dated today'}"] += 1
        self.touched = ("cash", hid) if kind == "cash" else target.key

    # ---- sell ---------------------------------------------------------------------------------
    def mf_model_cost(self, hold: HM, qty: Decimal) -> Decimal:
        """The cost of selling `qty` of a fund in part, from the machine's own bookkeeping (an oracle, kept
        simple). With transactions whose net units match the units held (0.01) AND an invested amount within
        1.00 of the cost of the lots still held: FIFO over the transactions. Otherwise (an edited cost, SIP
        rows behind it, no transactions yet) the invested amount pro rata. Never more than invested."""
        rows = self.h.rows(
            "SELECT kind, units, amount, txn_date FROM mf_transactions WHERE mutual_fund_id = :i "
            "ORDER BY txn_date, id", i=hold.id,
        )  # fmt: skip
        held, invested = hold.qty, hold.invested

        def take(lots: list, want: Decimal) -> Decimal:
            cost = ZERO
            for lot in lots:
                if want <= 0:
                    break
                use = min(lot[0], want)
                part = lot[1] if use == lot[0] else lot[1] * use / lot[0]
                lot[0] -= use
                lot[1] -= part
                want -= use
                cost += part
            return cost

        net = sum((Decimal(str(t.units)) * (1 if t.kind == "purchase" else -1) for t in rows), ZERO)
        pro_rata = q2(invested * qty / held)
        cost = pro_rata
        if rows and abs(net - held) <= Decimal("0.01"):
            lots: list = []
            for t in sorted(rows, key=lambda t: (t.txn_date, t.kind != "purchase")):
                if t.kind == "purchase":
                    lots.append([Decimal(str(t.units)), Decimal(str(t.amount))])
                else:
                    take(lots, Decimal(str(t.units)))
            lots = [lot for lot in lots if lot[0] > 0]
            left = sum((lot[0] for lot in lots), ZERO)
            if abs(q2(take([list(lot) for lot in lots], min(held, left))) - invested) <= Decimal("1.00"):
                cost = q2(take(lots, qty))
                TALLY["mf partial sale: FIFO" + (" after an edit" if hold.cost_edited else "")] += 1
            elif hold.cost_edited:
                TALLY["mf partial sale: pro rata of an edited cost, with transactions"] += 1
            else:
                TALLY["mf partial sale: pro rata, cost differs from the lots, not edited"] += 1
        elif hold.cost_edited:
            TALLY["mf partial sale: pro rata of an edited cost, units do not match"] += 1
        return min(cost, invested)

    def pick_dest(self, data):
        kind = data.draw(st.sampled_from(["none", "existing", "existing", "existing", "existing", "dead", "new", "new"]))
        if kind == "existing" and self.live_cash():
            c = data.draw(st.sampled_from(self.live_cash()))
            return {"kind": "cash_existing", "cash_id": c.id}, c, "ok"
        if kind == "dead" and self.dead_cash():
            c = data.draw(st.sampled_from(self.dead_cash()))
            return {"kind": "cash_existing", "cash_id": c.id}, c, "dead"
        if kind == "new":
            return {"kind": "cash_new", "cash_name": self.name("Proceeds")}, None, "new"
        return {"kind": "none"}, None, "none"

    def credit(self, r, dest, cash, how, amount, kind_label):
        """Update the cash model after an exit; returns (cash id, added)."""
        data = r.json()
        cid = data["cash_holding_id"]
        if how == "none":
            if cid is not None:
                self.fail(f"{kind_label}: no destination but cash_holding_id={cid}")
            return None, ZERO
        if how == "new":
            if cid is None or cid in self.cash:
                self.fail(f"{kind_label}: new account id {cid} is missing or already known")
            self.cash[cid] = CashM(cid, dest["cash_name"], "savings", amount, ZERO)
            return cid, amount
        if cid != cash.id:
            self.fail(f"{kind_label}: money went to {cid}, expected {cash.id}")
        cash.bal += amount
        return cid, amount

    def resend(self, what: str, method: str, url: str, want: tuple[int, ...], prefix: str | None = None, **kwargs):
        """The same request again right after it succeeded: it must be refused as `want`, and no row of
        any table may change (so no second money move)."""
        before = self.h.snapshot()
        r = self.h.call(method, url, **kwargs)
        self.expect(r, want, f"{what} again", prefix)
        if self.h.snapshot() != before:
            self.fail(f"{what} again ({r.status_code}) changed the database")
        return r

    @precondition(lambda self: bool(self.holds_of(*SELLABLE)))
    @rule(data=st.data())
    def sell(self, data):
        self.do_sell(data, repeat=False)

    @precondition(lambda self: bool(self.holds_of(*SELLABLE)))
    @rule(data=st.data())
    def sell_twice(self, data):
        """Double submit: a full sale, then the same request again (409: it is closed now)."""
        self.do_sell(data, repeat=True)

    def do_sell(self, data, repeat: bool):
        good = [h for h in self.holds_of(*SELLABLE, live=True) if not h.closed and not (h.slug == "bond" and h.matured)]
        hold = self.choose(data, good, self.holds_of(*SELLABLE))
        slug, today = hold.slug, self.h.today
        dest, cash, how = self.pick_dest(data)
        kind = "all" if slug == "other" or repeat else data.draw(st.sampled_from(["part", "part", "all", "all", "over"]))
        body: dict = {"destination": dest}
        held = hold.qty
        if slug == "other":
            gross = from_cents(data.draw(st.integers(100, 5_000_000)))
            body["amount"], qty, full = sx(gross), None, True
        else:
            whole = slug in ("stock", "bond")
            step = Decimal(1) if whole else Decimal("0.001")
            if kind == "all" or held < 2 * step:
                qty = held
            elif kind == "over":
                qty = held + step
            else:
                lo = 1
                hi = int(held / step) - 1
                qty = step * data.draw(st.integers(lo, hi))
            price = from_cents(data.draw(st.integers(100, 300_000)))
            body["quantity"] = sx(qty) if not whole else int(qty)
            body["price"] = sx(price)
            gross = q2(qty * price)
            full = qty == held
        edge = data.draw(st.sampled_from(["zero", "zero", "some", "edge"]))
        charges = ZERO
        if edge == "some" and gross > 1:
            charges = from_cents(data.draw(st.integers(0, int(gross * 100) - 1)))
        elif edge == "edge":
            charges = gross
        body["charges"] = sx(charges)
        if slug == "mf":
            sale_date = today
        else:
            back = (today - hold.start).days if hold.start else 300
            sale_date = today - timedelta(days=data.draw(st.integers(0, min(300, back))))
        body["date"] = sale_date.isoformat()
        amount = gross - charges

        # prediction ----------------------------------------------------------------------------
        invested = hold.inv()
        cost = None
        if not hold.live:
            allowed, prefix = (404,), None
        elif hold.closed or (slug == "bond" and hold.matured):
            allowed, prefix = (409,), None
        elif (slug != "other" and qty > held) or gross <= 0 or charges >= gross or how == "dead":
            allowed, prefix = (422,), None
        elif full:
            allowed, prefix = (201,), None
            cost = q2(invested) if invested is not None else ZERO
        else:
            allowed, prefix = (201,), None
            if slug == "mf":
                allowed = (201, 422)  # the cost floor may refuse: only with its message
                cost = self.mf_model_cost(hold, qty)
            else:
                cost = q2(invested * qty / held)
                if q2(invested - cost) < CENT:
                    allowed, prefix = (422,), REFUSED
        if allowed == (201,) and not full and cost is None:
            self.fail("model error: no cost predicted")

        pre = self.db_state(hold)
        r = self.h.call("POST", f"/api/holdings/{slug}/{hold.id}/sell", json=body)
        status = self.expect(r, allowed, f"sell {slug}", prefix if r.status_code == 422 and prefix else None)
        if slug == "mf" and allowed == (201, 422) and status == 422:
            if reason(r) != REFUSED:
                self.fail(f"sell mf: 422 with an unexpected message {reason(r)!r}")
            TALLY["mf partial sale refused by the cost floor"] += 1
        if status >= 400:
            return
        out = r.json()
        if out["closed"] != full or d(out["amount"]) != amount:
            self.fail(f"sell {slug}: closed/amount {out['closed']}/{out['amount']} != {full}/{amount}")
        if cost is not None and d(out["cost"]) != cost:
            self.fail(f"sell {slug}: cost {out['cost']} != predicted {cost}")
        cash_id, added = self.credit(r, dest, cash, how, amount, f"sell {slug}")
        ex = ExitM(out["id"], slug, hold.id, "sale", cash_id, added, amount,
                   None if slug == "other" else qty, full, pre=pre)  # fmt: skip
        self.exits[ex.id] = ex
        hold.exits.append(ex.id)
        if full:
            hold.closed = True
        elif slug in ("bond", "gold"):
            hold.qty -= qty
            hold.invested = q2(hold.invested - cost)
        else:
            hold.qty -= qty
        if slug == "mf":
            self.refresh_mf()
        ex.post = self.db_state(hold)
        if ex.post[0] != (pre[0] if full else pre[0] - qty) and slug != "other":
            self.fail(f"sell {slug}: quantity after {ex.post[0]} (before {pre[0]}, sold {qty})")
        if slug == "mf" and not full and ex.post[1] != q2(pre[1] - cost):
            self.fail(f"sell mf: invested after {ex.post[1]} != before {pre[1]} less the sale cost {cost}")
        self.touched = hold.key
        if slug == "mf" and not repeat and self.buys and data.draw(st.booleans()):
            # right after the sale: a buy dated on or before it can't be undone (409) while it stands
            mine = sorted((b for b in self.buys.values() if b.hid == hold.id), key=lambda b: b.id)
            if mine:
                self.do_undo_buy(data, repeat=False, buy=data.draw(st.sampled_from([b for b in mine if b.when == self.h.today] or mine)))
        if repeat and full:
            self.resend(f"sell {slug}", "POST", f"/api/holdings/{slug}/{hold.id}/sell", (409,), json=body)
        elif not repeat and ex.added > 0 and ex.cash_id is not None and data.draw(st.sampled_from([True, False, False, False])):
            self.spend_and_undo(data, ex)

    # ---- settle -------------------------------------------------------------------------------
    @precondition(lambda self: bool(self.holds_of(*SETTLEABLE)))
    @rule(data=st.data())
    def settle(self, data):
        self.do_settle(data, repeat=False)

    @precondition(lambda self: bool(self.holds_of(*SETTLEABLE)))
    @rule(data=st.data())
    def settle_twice(self, data):
        """Double submit: a settlement, then the same request again (409: already settled)."""
        self.do_settle(data, repeat=True)

    def do_settle(self, data, repeat: bool):
        good = [h for h in self.holds_of(*SETTLEABLE, live=True) if h.matured and not h.settled]
        hold = self.choose(data, good, self.holds_of(*SETTLEABLE))
        dest, cash, how = self.pick_dest(data)
        explicit = data.draw(st.sampled_from([True, True, True, False]))
        body: dict = {"destination": dest}
        amount = None
        if explicit:
            amount = from_cents(data.draw(st.integers(100, 5_000_000)))
            body["amount"] = sx(amount)
        if not hold.live:
            allowed = (404,)
        elif hold.settled or not hold.matured:
            allowed = (409,)
        elif how == "dead":
            allowed = (422,)
        else:
            allowed = (201,)
        r = self.h.call("POST", f"/api/holdings/{hold.slug}/{hold.id}/settle", json=body)
        if self.expect(r, allowed, f"settle {hold.slug}") >= 400:
            return
        out = r.json()
        amount = d(out["amount"]) if amount is None else amount
        if d(out["amount"]) != amount:
            self.fail(f"settle: amount {out['amount']} != {amount}")
        cash_id, added = self.credit(r, dest, cash, how, amount, "settle")
        ex = ExitM(out["id"], hold.slug, hold.id, "maturity", cash_id, added, amount, None, True)
        self.exits[ex.id] = ex
        hold.exits.append(ex.id)
        hold.settled = True
        self.touched = hold.key
        if repeat:
            self.resend(f"settle {hold.slug}", "POST", f"/api/holdings/{hold.slug}/{hold.id}/settle", (409,), json=body)
        elif ex.added > 0 and ex.cash_id is not None and data.draw(st.sampled_from([True, False, False, False])):
            self.spend_and_undo(data, ex)

    # ---- undo ---------------------------------------------------------------------------------
    @precondition(lambda self: bool(self.exits))
    @rule(data=st.data())
    def undo(self, data):
        self.do_undo(data, repeat=False)

    @precondition(lambda self: bool(self.exits))
    @rule(data=st.data())
    def undo_twice(self, data):
        """Double submit: an undo, then the same request again (404: the record is gone)."""
        self.do_undo(data, repeat=True)

    def paying_exits(self) -> list[ExitM]:
        """Exits that put money into a live account (what an undo has to take back out again)."""
        return sorted(
            (e for e in self.exits.values() if e.added > 0 and e.cash_id is not None and self.cash[e.cash_id].live),
            key=lambda e: e.id,
        )

    @precondition(lambda self: bool(self.paying_exits()))
    @rule(data=st.data())
    def spend_then_undo(self, data):
        """Sell or settle into an account, spend from that account, then undo the exit. The undo is refused
        (409 "Not enough in") exactly while the account holds less than the exit paid in, and by the reinvest
        rule while a holding was paid from the exit; the spend is a PUT of the balance or a Paid From add."""
        paying = self.paying_exits()
        latest = [e for e in paying if self.holds[(e.slug, e.hid)].live and e.id == max(self.holds[(e.slug, e.hid)].exits)]
        self.spend_and_undo(data, self.choose(data, latest, paying))

    def spend_and_undo(self, data, ex: ExitM) -> None:
        """The body of spend_then_undo; a sale or settlement into an account also chains it (one time in four)
        so a run reaches the combination however few steps it has."""
        cash = self.cash[ex.cash_id]
        added = int(ex.added * 100)
        # the balance left after the spend: 1 cent short, anywhere short, exactly enough, or more than enough
        left = data.draw(st.one_of(
            st.just(max(added - 1, 0)), st.integers(0, max(added - 1, 0)), st.just(added), st.integers(added, added + 100_000),
        ))  # fmt: skip
        if data.draw(st.booleans()):
            body = {"name": cash.name, "kind": cash.kind, "balance": sx(from_cents(left)), "balance_date": "2026-01-01"}
            r = self.h.call("PUT", f"/api/assets/cash/{cash.id}", json=body)
            if self.expect(r, (200,), "put cash") < 400:
                cash.bal, cash.put = from_cents(left), True
        else:
            spend = int(cash.bal * 100) - left
            if spend > 0:
                tmpl, hold, amount = self.build(data, "other", spend)
                self.create("other", tmpl, hold, amount, cash)
        TALLY["spend then undo"] += 1
        self.do_undo(data, repeat=False, ex=ex)

    def do_undo(self, data, repeat: bool, ex: ExitM | None = None):
        if ex is None:
            stale = [i for i in self.gone if i not in self.exits]
            if stale and data.draw(st.sampled_from([False] * 12 + [True])):
                r = self.h.call("DELETE", f"/api/exits/{stale[-1]}")
                self.expect(r, (404,), "undo gone")
                return
            good = [
                e for e in self.exits.values()
                if self.holds[(e.slug, e.hid)].live and e.id == max(self.holds[(e.slug, e.hid)].exits)
            ]  # fmt: skip
            ex = self.choose(data, sorted(good, key=lambda e: e.id), sorted(self.exits.values(), key=lambda e: e.id))
        hold = self.holds[(ex.slug, ex.hid)]
        cash = self.cash.get(ex.cash_id) if ex.cash_id is not None else None
        reinvested = any(f.active and f.from_exit == ex.id for h2 in self.holds.values() for f in h2.fundings)
        if not hold.live:
            allowed, prefix = (409,), "Holding not found"
        elif ex.id != max(hold.exits):
            allowed, prefix = (409,), "Undo the latest one first"
        elif reinvested:
            allowed, prefix = (409,), "Some of this money was reinvested"
        elif cash is not None and ex.added > cash.bal:
            allowed, prefix = (409,), "Not enough in"
        else:
            allowed, prefix = (200,), None
        before = self.db_state(hold) if hold.slug in SELLABLE else None
        r = self.h.call("DELETE", f"/api/exits/{ex.id}")
        if self.expect(r, allowed, f"undo {ex.kind}", prefix) >= 400:
            return
        del self.exits[ex.id]
        self.gone.append(ex.id)
        if self.h.local_pg:  # ON DELETE SET NULL on holding_fundings.from_exit_id (SQLite has no FKs)
            for other in self.holds.values():
                for f in other.fundings:
                    if f.from_exit == ex.id:
                        f.from_exit = None
        hold.exits.remove(ex.id)
        if cash is not None:
            cash.bal -= ex.added
        if ex.kind == "maturity":
            hold.settled = False
        elif ex.full:
            hold.closed = False
        elif hold.slug in ("bond", "gold"):
            hold.qty += ex.qty
            hold.invested = q2(hold.invested + d(self._cost_of(ex)))
        else:
            hold.qty += ex.qty
        if hold.slug == "mf":
            self.refresh_mf()
        if ex.kind == "sale" and before == ex.post:
            after = self.db_state(hold)
            if after != ex.pre:
                self.fail(f"sell-then-undo: state {after} != the state before the sale {ex.pre}")
        self.touched = hold.key
        if repeat:
            self.resend(f"undo {ex.kind}", "DELETE", f"/api/exits/{ex.id}", (404,))

    def _cost_of(self, ex: ExitM) -> Decimal:
        """The cost the app recorded for an exit (read before it was deleted is not possible: use pre)."""
        # pre.invested - post.invested is exactly the cost of a partial sale
        return q2(ex.pre[1] - ex.post[1])

    # ---- buy more and undo a buy (SPEC §8d) -----------------------------------------------------
    @staticmethod
    def _day(value) -> date | None:
        return None if value is None else date.fromisoformat(str(value)[:10])

    def fund_dates(self, hold: HM) -> tuple[date, date | None]:
        """(purchase date, date of the latest sale) of a fund from the ledger rows: sale exits and every
        redemption transaction."""
        purchase = self._day(self.h.scalar("SELECT purchase_date FROM mutual_funds WHERE id = :i", i=hold.id))
        sold = self._day(self.h.scalar(
            "SELECT max(exit_date) FROM holding_exits WHERE asset_type = 'mf' AND holding_id = :i AND kind = 'sale'",
            i=hold.id,
        ))  # fmt: skip
        redeemed = self._day(self.h.scalar(
            "SELECT max(txn_date) FROM mf_transactions WHERE mutual_fund_id = :i AND kind = 'redemption'", i=hold.id
        ))  # fmt: skip
        dates = [x for x in (sold, redeemed) if x is not None]
        return purchase, (max(dates) if dates else None)

    @precondition(lambda self: bool(self.holds_of("mf")))
    @rule(data=st.data())
    def buy_more(self, data):
        self.do_buy(data, repeat=False)

    @precondition(lambda self: bool(self.holds_of("mf")))
    @rule(data=st.data())
    def buy_more_twice(self, data):
        """Double submit: a buy, then the same request again (409 "looks like a buy you already made", nothing
        changes); then sometimes the same request with confirm_duplicate=true, which adds a second purchase."""
        self.do_buy(data, repeat=True)

    def do_buy(self, data, repeat: bool):
        self.refresh_mf()
        funds = self.holds_of("mf")
        hold = self.choose(data, [h for h in funds if h.live and not h.closed], funds)
        today = self.h.today
        purchase, last_sale = self.fund_dates(hold)
        mine = sorted((b for b in self.buys.values() if b.hid == hold.id), key=lambda b: b.id)
        if mine and not repeat and data.draw(st.sampled_from([False, False, False, True])):
            again = data.draw(st.sampled_from(mine))  # the same buy as one already recorded
            when, amount, units = again.when, again.amount, again.units
        else:
            low = max(purchase, last_sale) if last_sale is not None else purchase
            span = max(0, (today - low).days)
            kind = data.draw(st.sampled_from(["ok"] * 9 + ["future", "early"]))
            if kind == "future":
                when = today + timedelta(days=data.draw(st.integers(1, 5)))
            elif kind == "early":
                base = last_sale if last_sale is not None and data.draw(st.booleans()) else purchase
                when = base - timedelta(days=data.draw(st.integers(1, 5)))
            else:
                offset = data.draw(st.one_of(st.just(0), st.just(span), st.integers(0, span)))
                when = low + timedelta(days=offset)
            amount = from_cents(data.draw(st.integers(100, 2_000_000)))
            units = None
        nav = Decimal(data.draw(st.integers(100_000, 3_000_000))).scaleb(-4)
        if units is None and data.draw(st.sampled_from([False, False, True])):
            units = from_milli(data.draw(st.integers(1, 300_000)))
        explicit = units is not None
        if units is None:
            units = q3(amount / nav)
        status = self.buy_once(data, hold, when, amount, nav, units, explicit, confirm=False, repeat=repeat)
        if repeat and status == 201:
            if data.draw(st.sampled_from([True, False, False])):
                self.buy_once(data, hold, when, amount, nav, units, explicit, confirm=True, repeat=False)

    def buy_once(self, data, hold: HM, when: date, amount: Decimal, nav: Decimal, units: Decimal,
                 explicit: bool, confirm: bool, repeat: bool) -> int:  # fmt: skip
        from app.schemas.buys import BUY_DATE_BEFORE_LAST_SALE_ERROR, BUY_DUPLICATE_MESSAGE
        from app.schemas.exits import EXIT_DATE_FUTURE_ERROR, SELL_DATE_BEFORE_PURCHASE_ERROR

        today = self.h.today
        purchase, last_sale = self.fund_dates(hold)
        dup = any(
            b.hid == hold.id and (b.when, b.amount, b.units) == (when, amount, units) for b in self.buys.values()
        )
        prefix = None
        if not hold.live:
            want = 404
        elif hold.closed:
            want = 409
        elif when > today:
            want, prefix = 422, EXIT_DATE_FUTURE_ERROR
        elif when < purchase:
            want, prefix = 422, SELL_DATE_BEFORE_PURCHASE_ERROR
        elif last_sale is not None and when < last_sale:
            want, prefix = 422, BUY_DATE_BEFORE_LAST_SALE_ERROR
        elif dup and not confirm:
            want, prefix = 409, BUY_DUPLICATE_MESSAGE
        else:
            want = 201
        body = {"date": when.isoformat(), "amount": sx(amount), "nav": sx(nav)}
        if explicit:
            body["units"] = sx(units)
        url = f"/api/holdings/mf/{hold.id}/buy"
        params = {"confirm_duplicate": "true"} if confirm else None
        sold_in_part = any(self.exits[e].kind == "sale" for e in hold.exits)
        pre_state = self.db_state(hold) if hold.live else None
        r = self.h.call("POST", url, params=params, json=body)
        if self.expect(r, (want,), "buy more", prefix) >= 400:
            return r.status_code
        out = r.json()
        total_units, total_invested = hold.qty + units, hold.invested + amount
        avg_nav = (total_invested / total_units).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        got = (d(out["units_added"]), d(out["units"]), d(out["invested_amount"]), d(out["avg_nav"]))
        if got != (units, total_units, total_invested, avg_nav):
            self.fail(f"buy more: result {got} != {(units, total_units, total_invested, avg_nav)}")
        row = self.h.rows(
            "SELECT mutual_fund_id, txn_date, kind, amount, units, sip_id, manual FROM mf_transactions WHERE id = :i",
            i=out["transaction_id"],
        )  # fmt: skip
        if len(row) != 1:
            self.fail("buy more: the purchase row is missing")
        t = row[0]
        if (t.mutual_fund_id, self._day(t.txn_date), t.kind, q2(t.amount), q3(t.units), t.sip_id, bool(t.manual)) != (
            hold.id, when, "purchase", amount, units, None, True,
        ):  # fmt: skip
            self.fail(f"buy more: the stored purchase differs: {tuple(t)}")
        if self.fund_dates(hold)[0] != purchase:
            self.fail("buy more: the purchase date moved")
        self.buys[out["transaction_id"]] = BuyM(out["transaction_id"], hold.id, when, amount, units)
        hold.qty, hold.invested = total_units, total_invested
        TALLY["buy more: " + ("partly sold fund" if sold_in_part else "fund")] += 1
        if confirm:
            TALLY["buy more: confirmed duplicate"] += 1
        if pre_state is not None and self.db_state(hold) != (total_units, total_invested, False):
            self.fail(f"buy more: fund state {self.db_state(hold)} after buying onto {pre_state}")
        self.touched = hold.key
        if repeat:
            self.resend("buy more", "POST", url, (409,), BUY_DUPLICATE_MESSAGE, params=params, json=body)
        return 201

    @precondition(lambda self: bool(self.buys))
    @rule(data=st.data())
    def undo_buy(self, data):
        self.do_undo_buy(data, repeat=False)

    @precondition(lambda self: bool(self.buys))
    @rule(data=st.data())
    def undo_buy_twice(self, data):
        """Double submit: an undo, then the same request again (404: the record is gone)."""
        self.do_undo_buy(data, repeat=True)

    def do_undo_buy(self, data, repeat: bool, buy: BuyM | None = None):
        from app.schemas.buys import BUY_UNDO_REFUSED_MESSAGE, BUY_UNDO_SALE_FIRST_MESSAGE

        self.refresh_mf()
        if buy is None:
            every = sorted(self.buys.values(), key=lambda b: b.id)
            good = [b for b in every if self.holds[("mf", b.hid)].live and not self.holds[("mf", b.hid)].closed]
            buy = self.choose(data, good, every)
        hold = self.holds[("mf", buy.hid)]
        _, last_sale = self.fund_dates(hold)
        left, left_invested = hold.qty - buy.units, hold.invested - buy.amount
        prefix = None
        if not hold.live:
            want, prefix = 404, "Holding not found"
        elif hold.closed:
            want, prefix = 409, "Already sold"
        elif last_sale is not None and last_sale >= buy.when:
            want, prefix = 409, BUY_UNDO_SALE_FIRST_MESSAGE
            TALLY["undo buy: refused, a sale on or after it"] += 1
        elif left <= 0 or left_invested < floor_of("mf", left):
            want, prefix = 409, BUY_UNDO_REFUSED_MESSAGE
        else:
            want = 200
        url = f"/api/holdings/mf/{hold.id}/buys/{buy.id}"
        r = self.h.call("DELETE", url)
        if self.expect(r, (want,), "undo buy", prefix) >= 400:
            return
        if self.h.scalar("SELECT count(*) FROM mf_transactions WHERE id = :i", i=buy.id):
            self.fail("undo buy: the purchase row is still there")
        del self.buys[buy.id]
        hold.qty, hold.invested = left, q2(left_invested)
        if self.db_state(hold) != (left, q2(left_invested), False):
            self.fail(f"undo buy: fund state {self.db_state(hold)} != {(left, q2(left_invested))}")
        self.touched = hold.key
        if repeat:
            self.resend("undo buy", "DELETE", url, (404,), "Record not found")

    # ---- delete / restore ---------------------------------------------------------------------
    def items(self) -> list:
        key = lambda i: (type(i).__name__, getattr(i, "slug", ""), i.id)  # noqa: E731
        return sorted([*self.holds.values(), *self.cash.values()], key=key)

    def choose(self, data, good: list, anything: list):
        """Mostly a `good` candidate (so most steps are valid), sometimes any (a legal rejection)."""
        pool = good if good and data.draw(st.sampled_from([True] * 6 + [False])) else anything
        return data.draw(st.sampled_from(pool))

    @precondition(lambda self: any(i.live for i in self.items()))
    @rule(data=st.data())
    def delete(self, data):
        self.do_delete(data, repeat=False)

    @precondition(lambda self: any(i.live for i in self.items()))
    @rule(data=st.data())
    def delete_twice(self, data):
        """Double submit: a delete, then the same request again (404: already deleted, no second refund)."""
        self.do_delete(data, repeat=True)

    def linked_cash(self) -> list[CashM]:
        """Live accounts an exit or a funding points at (what a purge of the account must set to NULL)."""
        ids = {e.cash_id for e in self.exits.values()} | {f.cash_id for h in self.holds.values() for f in h.fundings}
        return [c for c in self.live_cash() if c.id in ids]

    @precondition(lambda self: bool(self.linked_cash()))
    @rule(data=st.data())
    def delete_linked_cash(self, data):
        """Delete an account that exits or fundings point at (so a later purge has links to set to NULL)."""
        self.do_delete(data, repeat=False, only=self.linked_cash())

    def do_delete(self, data, repeat: bool, only: list | None = None):
        items = self.items()
        # Mostly holdings that can be deleted (no sale or settlement on record), sometimes any.
        free = [i for i in items if i.live and not (isinstance(i, HM) and i.exits)]
        with_exits = [i for i in items if i.live and isinstance(i, HM) and i.exits]
        if only:
            item = data.draw(st.sampled_from(only))
        elif with_exits and not repeat and data.draw(st.sampled_from([False, True, True])):
            item = data.draw(st.sampled_from(with_exits))  # the delete guard: refused while an exit exists
        else:
            item = self.choose(data, free, items)
        slug = item.slug if isinstance(item, HM) else "cash"
        # DELETE-409 contract (web/lib/delete-guard.ts disables Delete on the same rule): a holding is
        # refused with 409 exactly while it has at least one sale or settlement on record (the model's
        # exit list: an undo removes the exit, so it is deletable again); otherwise it is deleted.
        # Cash accounts have no exits of their own and are always deletable.
        if not item.live:
            want, prefix = (404,), None
        elif isinstance(item, HM) and item.exits:  # a sold or settled holding can't be deleted
            kinds = {self.exits[e].kind for e in item.exits}
            want, prefix = (409,), "Undo the sale first" if "sale" in kinds else "Undo the settlement first"
        else:
            want, prefix = (200,), None
        r = self.h.call("DELETE", f"/api/assets/{slug}/{item.id}")
        if self.expect(r, want, f"delete {slug}", prefix) >= 400:
            return
        item.live, item.del_day = False, self.h.today
        for f in getattr(item, "fundings", []):
            if f.active:  # the ideal ledger: the refund goes back whether or not the account is deleted
                if f.cash_id is not None:  # a purged account: no money moves, only refunded_at is set
                    self.cash[f.cash_id].bal += f.amount
                f.active = False
        if repeat:
            self.resend(f"delete {slug}", "DELETE", f"/api/assets/{slug}/{item.id}", (404,))

    @precondition(lambda self: any(not i.live for i in self.items()))
    @rule(data=st.data())
    def restore(self, data):
        self.do_restore(data, repeat=False)

    @precondition(lambda self: any(not i.live for i in self.items()))
    @rule(data=st.data())
    def restore_twice(self, data):
        """Double submit: a restore, then the same request again (404: not deleted any more, no second debit)."""
        self.do_restore(data, repeat=True)

    def do_restore(self, data, repeat: bool):
        item = self.choose(data, [i for i in self.items() if not i.live], self.items())
        slug = item.slug if isinstance(item, HM) else "cash"
        want, prefix = (404,), None
        if not item.live:
            want, bal = (200,), {c.id: c.bal for c in self.cash.values()}
            for f in getattr(item, "fundings", []):
                if not f.active and f.cash_id is not None:
                    if bal[f.cash_id] < f.amount:
                        want, prefix = (409,), "Not enough in"
                        break
                    bal[f.cash_id] -= f.amount
        r = self.h.call("POST", f"/api/assets/{slug}/{item.id}/restore")
        if self.expect(r, want, f"restore {slug}", prefix) >= 400:
            return
        item.live, item.del_day = True, None
        for f in getattr(item, "fundings", []):
            if not f.active:
                if f.cash_id is not None:
                    self.cash[f.cash_id].bal -= f.amount
                f.active = True
        self.touched = item.key if isinstance(item, HM) else None
        if repeat:
            self.resend(f"restore {slug}", "POST", f"/api/assets/{slug}/{item.id}/restore", (404,))

    # ---- purge (time passes, then the retention clean-up runs) ----------------------------------------
    @rule(data=st.data())
    def purge_after(self, data):
        """Let days pass, then purge (SPEC §4 soft delete, §8b, §8c). The purge measures age against the real
        wall clock, so before it runs every deleted row is back-dated to the age the harness clock gives it
        (harness.backdate_deleted; app code is not patched). Past retention (more than 30 days; exactly 30 is
        kept): the holding is gone for good with its exits, fundings and MF transactions (restore is then 404);
        a purged cash account is gone and the exits and fundings that pointed at it stay with the link NULL,
        no balance changes anywhere; everything deleted less than 30 days ago is untouched. The counts the
        purge returns are the model's. A second run, through the other entry point, removes nothing."""
        self.purge_run(data, data.draw(st.sampled_from([0, 1, 30, 31, 31, 45])))

    @precondition(
        lambda self: self.h.today <= LAST_TODAY - timedelta(days=31)
        and any(e.cash_id in {c.id for c in self.live_cash()} for e in self.exits.values())
    )
    @rule(data=st.data())
    def purge_exit_cash(self, data):
        """Delete an account an exit paid into, wait past retention, purge: the exit stays with a NULL link."""
        live = {c.id for c in self.live_cash()}
        paid = [self.cash[e.cash_id] for e in self.exits.values() if e.cash_id in live]
        self.do_delete(data, repeat=False, only=paid)
        self.purge_run(data, 31)

    def purge_run(self, data, days: int):
        self.h.today +=timedelta(days=min(days, max(0, (LAST_TODAY - self.h.today).days)))
        today = self.h.today
        dead = [i for i in self.items() if not i.live]
        for item in dead:
            table = TABLES["cash" if isinstance(item, CashM) else item.slug]
            self.h.backdate_deleted(table, item.id, (today - item.del_day).days)
        old = [i for i in dead if (today - i.del_day).days > RETENTION_DAYS]
        old_holds = [i for i in old if isinstance(i, HM)]
        old_cash = [i for i in old if isinstance(i, CashM)]
        want = {slug: 0 for slug in ("fd", "rd", "stock", "bond", "mf", "nps", "gold", "cash", "pf", "other")}
        for i in old:
            want["cash" if isinstance(i, CashM) else i.slug] += 1
        want["exits"] = sum(len(hold.exits) for hold in old_holds)
        want["fundings"] = sum(len(hold.fundings) for hold in old_holds)
        balances = {c.id: c.bal for c in self.cash.values()}
        TALLY["purge steps"] += 1
        if old:
            TALLY["purge removed something"] += 1
        if old_cash:
            TALLY["purge removed a cash account"] += 1
        if any(f.cash_id in {c.id for c in old_cash} for hold in self.holds.values() for f in hold.fundings):
            TALLY["purge nulled a funding's cash link"] += 1
        if any(e.cash_id in {c.id for c in old_cash} for e in self.exits.values()):
            TALLY["purge nulled an exit's cash link"] += 1
        if any(hold.slug == "mf" for hold in old_holds):
            TALLY["purge removed a fund"] += 1
        if len(dead) > len(old):
            TALLY["purge kept a recent deletion"] += 1

        first_by_cron = data.draw(st.booleans())
        counts = self.h.purge(via_cron=first_by_cron)
        if counts != want:
            self.fail(f"purge removed {counts}, the model expects {want}")

        # the model after the purge
        gone_ids = {e for hold in old_holds for e in hold.exits}
        for e in gone_ids:
            self.gone.append(e)
            del self.exits[e]
        for hold in old_holds:
            del self.holds[hold.key]
        purged_funds = {hold.id for hold in old_holds if hold.slug == "mf"}
        self.buys = {i: b for i, b in self.buys.items() if b.hid not in purged_funds}  # their rows went too
        for hold in self.holds.values():
            for f in hold.fundings:
                if f.from_exit in gone_ids:
                    f.from_exit = None
        dead_ids = {c.id for c in old_cash}
        for c in old_cash:
            del self.cash[c.id]
        for e in self.exits.values():
            if e.cash_id in dead_ids:
                e.cash_id = None
        for hold in self.holds.values():
            for f in hold.fundings:
                if f.cash_id in dead_ids:
                    f.cash_id = None
        if {c.id: c.bal for c in self.cash.values()} != {k: v for k, v in balances.items() if k not in dead_ids}:
            self.fail("model error: a purge changed a balance")  # no money moves in a purge

        # purged for good: restore, read and delete are 404 and change nothing
        for item in [*old_holds, *old_cash][:6]:
            slug = item.slug if isinstance(item, HM) else "cash"
            self.resend(f"restore purged {slug}", "POST", f"/api/assets/{slug}/{item.id}/restore", (404,))
            self.resend(f"get purged {slug}", "GET", f"/api/assets/{slug}/{item.id}", (404,))
            self.resend(f"delete purged {slug}", "DELETE", f"/api/assets/{slug}/{item.id}", (404,))
        fund_ids = [hold.id for hold in old_holds if hold.slug == "mf"]
        if fund_ids and self.h.scalar(
            "SELECT count(*) FROM mf_sips WHERE mutual_fund_id IN (%s)" % ",".join(str(i) for i in fund_ids)
        ):
            self.fail("a SIP still points at a purged fund")  # noqa: S608

        # idempotent: the same purge again, through the other entry point, is a no-op
        before = self.h.snapshot()
        again = self.h.purge(via_cron=not first_by_cron)
        if any(again.values()):
            self.fail(f"the second purge removed {again}")
        if self.h.snapshot() != before:
            self.fail("the second purge changed the database")
        self.touched = None

    # ---- SIPs ---------------------------------------------------------------------------------
    @rule(data=st.data())
    def advance(self, data):
        if self.h.today >= LAST_TODAY - timedelta(days=2):
            return
        self.h.today += timedelta(days=data.draw(st.integers(1, 35)))

    @precondition(lambda self: len(self.sips) < 3)
    @rule(data=st.data())
    def sip_create(self, data):
        self.refresh_mf()
        body = {
            "scheme_code": SCHEME, "platform": data.draw(st.sampled_from(["Groww", "Zerodha"])),
            "amount": data.draw(st.integers(100, 20_000)), "day_of_month": data.draw(st.integers(1, 28)),
            "start_date": data.draw(st.sampled_from(["2026-01-05", "2026-02-01", "2026-03-01"])),
            "include_past": data.draw(st.sampled_from([True, True, False])),
        }  # fmt: skip
        want = 201
        funds = self.holds_of("mf")
        if funds and data.draw(st.sampled_from([False, False, False, True])):
            fund = data.draw(st.sampled_from(funds))
            body["mutual_fund_id"] = fund.id
            want = 404 if not fund.live else 422 if fund.closed else 201
        frozen = self.frozen()
        r = self.h.call("POST", "/api/sips", params={"confirm_duplicate": "true"}, json=body)
        if self.expect(r, (want,), "sip create") >= 400:
            return
        self.sips[r.json()["id"]] = SipM(r.json()["id"], amount=body["amount"], day=body["day_of_month"])
        self.after_sip(frozen)

    @precondition(lambda self: len(self.sips) < 3)
    @rule(data=st.data())
    def sip_create_twice(self, data):
        """Double submit of a SIP create WITHOUT confirm_duplicate: 201 unless an active SIP with the same
        scheme, day and amount exists (then 409 with those SIPs listed); the same request again is then
        always 409 listing the new SIP, and adds no SIP and no instalment."""
        self.refresh_mf()
        body = {
            "scheme_code": SCHEME, "platform": data.draw(st.sampled_from(["Groww", "Zerodha"])),
            "amount": data.draw(st.sampled_from([100, 500, 2500])), "day_of_month": data.draw(st.sampled_from([5, 15, 28])),
            "start_date": data.draw(st.sampled_from(["2026-01-05", "2026-03-01"])),
            "include_past": data.draw(st.booleans()),
        }  # fmt: skip
        running = sorted(
            s.id for s in self.sips.values()
            if s.status == "active" and s.amount == body["amount"] and s.day == body["day_of_month"]
        )  # fmt: skip
        frozen = self.frozen()
        r = self.h.call("POST", "/api/sips", json=body)
        if running:
            self.expect(r, (409,), "sip create (duplicate)")
            ids = sorted(x["id"] for x in r.json()["duplicates"])
            if ids != running:
                self.fail(f"sip create: duplicates {ids} != the running SIPs {running}")
            return
        if self.expect(r, (201,), "sip create (plain)") >= 400:
            return
        sid = r.json()["id"]
        self.sips[sid] = SipM(sid, amount=body["amount"], day=body["day_of_month"])
        self.after_sip(frozen)
        again = self.resend("sip create", "POST", "/api/sips", (409,), json=body)
        if sorted(x["id"] for x in again.json()["duplicates"]) != sorted([*running, sid]):
            self.fail(f"sip create again: duplicates {again.json()['duplicates']} do not list SIP {sid}")

    @rule()
    def post_due(self):
        frozen = self.frozen()
        self.h.post_due()
        self.after_sip(frozen)

    def after_sip(self, frozen: dict[int, tuple]) -> None:
        self.refresh_mf()
        after = self.frozen()
        for fid, was in frozen.items():
            now = after.get(fid)
            if now != was:
                self.fail(f"SIP posting changed the closed or deleted fund {fid}: {was} -> {now}")

    @precondition(lambda self: bool(self.sips))
    @rule(data=st.data())
    def sip_toggle(self, data):
        self.do_toggle(data, repeat=False)

    @precondition(lambda self: bool(self.sips))
    @rule(data=st.data())
    def sip_toggle_twice(self, data):
        """Double submit: pause (or resume), then the same request again (409: wrong state now)."""
        self.do_toggle(data, repeat=True)

    def pick_sip(self, data) -> SipM:
        """Mostly a SIP that is not cancelled (a cancelled one only allows refusals)."""
        live = [s for s in sorted(self.sips) if self.sips[s].status != "stopped"]
        pool = live if live and data.draw(st.sampled_from([True] * 6 + [False])) else sorted(self.sips)
        return self.sips[data.draw(st.sampled_from(pool))]

    def do_toggle(self, data, repeat: bool):
        sip = self.pick_sip(data)
        right = {"active": "pause", "paused": "resume"}.get(sip.status)  # a cancelled SIP allows neither
        action = right if right and (repeat or data.draw(st.sampled_from([True] * 6 + [False]))) else (
            data.draw(st.sampled_from(["pause", "resume"])) if right is None else {"pause": "resume", "resume": "pause"}[right]
        )  # fmt: skip
        legal = action == right
        r = self.h.call("POST", f"/api/sips/{sip.id}/{action}")
        if self.expect(r, (200,) if legal else (409,), f"sip {action}") < 400:
            sip.status = "paused" if action == "pause" else "active"
            if repeat:
                self.resend(f"sip {action}", "POST", f"/api/sips/{sip.id}/{action}", (409,))

    @precondition(lambda self: bool(self.sips))
    @rule(data=st.data(), repeat=st.booleans())
    def sip_stop(self, data, repeat):
        """Cancel a SIP (409 when it already is); with repeat the same request is sent again (409)."""
        if not data.draw(st.sampled_from([True, False, False])):
            return  # cancelling is final and the machine allows only a few SIPs: keep it occasional
        sip = self.pick_sip(data)
        was_stopped = sip.status == "stopped"
        r = self.h.call("POST", f"/api/sips/{sip.id}/stop")
        if self.expect(r, (409,) if was_stopped else (200,), "sip stop") < 400:
            sip.status = "stopped"
            if repeat:
                self.resend("sip stop", "POST", f"/api/sips/{sip.id}/stop", (409,))

    # ---- double submit of a create ---------------------------------------------------------------
    @rule(data=st.data())
    def double_create(self, data):
        """The same create twice without confirm_duplicate (SPEC §4 "Duplicate warnings"): names are unique,
        so the first finds no match (201, or 422 when a Paid From can't be afforded); the same request again
        is then 409 listing the first holding and changes nothing (also no second Paid From debit; when the
        account can no longer afford it, the funding check comes first and says 422 instead). The same
        request with confirm_duplicate=true then adds a second holding (the documented 'Add anyway')."""
        slug = data.draw(st.sampled_from(["cash", "fd", "rd", "stock", "bond", "nps", "pf", "other"]))
        if slug == "cash":
            if len(self.cash) >= 4:
                return
            body = {
                "name": self.name("Dup acct"), "kind": "savings",
                "balance": sx(from_cents(data.draw(st.integers(0, 1_000_000)))), "balance_date": "2026-01-01",
            }  # fmt: skip
            r = self.h.call("POST", "/api/assets/cash", json=body)
            if self.expect(r, (201,), "add cash (plain)") >= 400:
                return
            first = r.json()["id"]
            self.cash[first] = CashM(first, body["name"], "savings", d(body["balance"]), d(body["balance"]))
            again = self.resend("add cash", "POST", "/api/assets/cash", (409,), json=body)
            if [x["id"] for x in again.json()["duplicates"]] != [first]:
                self.fail(f"add cash again: duplicates {again.json()['duplicates']} != [{first}]")
            return
        mode = data.draw(st.sampled_from(["none", "paid", "paid"]))
        pool = self.live_cash()
        cash = data.draw(st.sampled_from(pool)) if pool and mode == "paid" else None
        bal = int(cash.bal * 100) if cash is not None else 0
        forced = data.draw(st.integers(1, bal)) if bal > 0 and data.draw(st.booleans()) else None
        body, hold, amount = self.build(data, slug, forced)
        if slug == "stock":
            body.pop("master_id", None)  # a linked stock is compared by master and quantity, not by name
            hold.master_id = None
        template = replace(hold, exits=[], fundings=[])
        status, payload = self.create(slug, body, hold, amount, cash, confirm=False)
        if status >= 400:
            return
        if cash is not None and amount > cash.bal:
            r = self.h.call("POST", f"/api/assets/{slug}", json=payload)  # the funding check comes first
            self.expect(r, (422,), f"add {slug} again (short)", TOO_MUCH)
        else:
            again = self.resend(f"add {slug}", "POST", f"/api/assets/{slug}", (409,), json=payload)
            if [x["id"] for x in again.json()["duplicates"]] != [hold.id]:
                self.fail(f"add {slug} again: duplicates {again.json()['duplicates']} != [{hold.id}]")
        if data.draw(st.booleans()):
            self.create(slug, body, template, amount, cash, confirm=True)

    @rule(data=st.data())
    def add_rules_of_new_types(self, data):
        """Creates the API refuses or reshapes without any effect on money: a PPF without an opening date is 422
        (SPEC §2), an unknown NPS scheme is 422 "Choose a scheme", and an EPF or VPF given an opening date is saved
        with none (the date belongs to a PPF only). A refused create, even with Paid From, changes no row."""
        from app.schemas.assets import NPS_SCHEME_ERROR, PPF_OPENED_ERROR

        if not data.draw(st.sampled_from([True, False, False, False])):
            return  # a side check: keep it occasional so the valid share stays healthy
        which =data.draw(st.sampled_from(["ppf", "scheme", "opened"]))
        pool = self.live_cash()
        paid = {"cash_id": data.draw(st.sampled_from(pool)).id} if pool and data.draw(st.booleans()) else None
        extra = {"paid_from": paid} if paid else {}
        if which == "opened":
            body, hold, amount = self.build(data, "pf")
            body["kind"], body["opened_on"] = data.draw(st.sampled_from(["epf", "vpf"])), "2015-04-01"
            cash = self.cash[paid["cash_id"]] if paid else None
            if self.create("pf", body, hold, amount, cash)[0] < 400:
                got = self.h.call("GET", f"/api/assets/pf/{hold.id}")
                if got.status_code != 200 or got.json()["opened_on"] is not None:
                    self.fail(f"an {body['kind']} kept its opening date: {got.text[:200]}")
            return
        if which == "ppf":
            body = self.build(data, "pf")[0]
            body["kind"], body["opened_on"] = "ppf", None
            slug, prefix = "pf", PPF_OPENED_ERROR
        else:
            body = self.build(data, "nps")[0]
            body["scheme_id"] = "NOSUCHSCHEME"
            slug, prefix = "nps", NPS_SCHEME_ERROR
        before = self.h.snapshot()
        r = self.h.call("POST", f"/api/assets/{slug}", params={"confirm_duplicate": "true"}, json={**body, **extra})
        self.expect(r, (422,), f"add {slug} (invalid)", prefix)
        if self.h.snapshot() != before:
            self.fail(f"a refused {slug} create changed the database")

    # ---- the second user -----------------------------------------------------------------------
    @precondition(lambda self: len(self.u2cash) + len(self.u2hold) < 6)
    @rule(data=st.data())
    def u2_add(self, data):
        """The second user adds a cash account, an Other holding (with an amount invested), a stock, an NPS or an EPF."""
        kind = data.draw(st.sampled_from(["cash", "other", "stock", "stock", "nps", "pf"]))
        cents = data.draw(st.integers(100, 2_000_000))
        if kind == "cash":
            body = {
                "name": self.name("U2 acct"), "kind": "savings", "balance": sx(from_cents(cents)),
                "balance_date": "2026-01-01",
            }  # fmt: skip
        elif kind == "other":
            body = {
                "name": self.name("U2 plot"), "category": "Property", "current_value": 80000,
                "value_date": "2026-01-01", "invested_amount": sx(from_cents(cents)), "acquired_on": None,
            }  # fmt: skip
        elif kind == "nps":
            body = {
                "scheme_id": data.draw(st.sampled_from(self.h.nps_schemes)), "units": "12.5000",
                "contributed": sx(from_cents(cents)), "start_date": "2024-01-01",
            }  # fmt: skip
        elif kind == "pf":
            body = {
                "name": self.name("U2 pf"), "kind": "epf", "balance": "50000.00", "balance_date": "2026-01-01",
                "interest_rate": 8.25, "contributed": sx(from_cents(cents)),
            }  # fmt: skip
        else:
            qty = data.draw(st.integers(2, 30))
            body = {
                "name": self.name("U2 stock"), "exchange": "NSE", "quantity": qty,
                "avg_buy_price": sx(from_cents(cents)), "buy_date": "2025-01-01",
            }  # fmt: skip
        r = self.h.call("POST", f"/api/assets/{kind}", as_user=2, params={"confirm_duplicate": "true"}, json=body)
        if self.expect(r, (201,), f"user 2 add {kind}") >= 400:
            return
        new = r.json()["id"]
        if kind == "cash":
            self.u2cash[new] = from_cents(cents)
        elif kind in ("other", "nps", "pf"):
            self.u2hold.append((kind, new, from_cents(cents), None))
        else:
            self.u2hold.append(("stock", new, q2(body["quantity"] * from_cents(cents)), Decimal(body["quantity"])))

    @precondition(lambda self: bool(self.holds or self.cash or self.sips or self.u2hold))
    @rule(data=st.data())
    def cross_user(self, data):
        """The second user (or, for the second user's ids, user 1) calls the API with ids that belong to
        someone else. Every call is refused without effect: 404 for a holding, account, exit or SIP in the
        path or a SIP's holding in the body, 422 "Choose one of your accounts" for a cash id in a body
        (Paid From, from_exit_id, a sale's destination). The whole database is the same afterwards."""
        from app.schemas.exits import CASH_ACCOUNT_ERROR

        today = self.h.today.isoformat()
        sale = {"date": today, "price": "10.00", "charges": "0", "destination": {"kind": "none"}}
        other_body = {"name": "Cross", "category": "Property", "current_value": 10, "value_date": "2026-01-01"}
        cases: list[tuple] = []  # (label, method, url, kwargs, want status, message prefix, acting user)
        for item in self.items():
            slug = item.slug if isinstance(item, HM) else "cash"
            base = f"/api/assets/{slug}/{item.id}"
            cases += [
                (f"get {slug}", "GET", base, {}, 404, None, 2),
                (f"detail {slug}", "GET", f"/api/holdings/{slug}/{item.id}", {}, 404, None, 2),
                (f"exits of {slug}", "GET", f"/api/holdings/{slug}/{item.id}/exits", {}, 404, None, 2),
                (f"delete {slug}", "DELETE", base, {}, 404, None, 2),
                (f"restore {slug}", "POST", base + "/restore", {}, 404, None, 2),
            ]  # fmt: skip
            if item.live:
                cases.append((f"put {slug}", "PUT", base, {"put": True}, 404, None, 2))
            if slug in SELLABLE:
                body = {**sale, "amount": "10.00"} if slug == "other" else {**sale, "quantity": 1}
                body = {k: v for k, v in body.items() if not (slug == "other" and k in ("price", "quantity"))}
                cases.append((f"sell {slug}", "POST", f"/api/holdings/{slug}/{item.id}/sell", {"json": body}, 404, None, 2))
            if slug in SETTLEABLE:
                cases.append((f"settle {slug}", "POST", f"/api/holdings/{slug}/{item.id}/settle",
                              {"json": {"destination": {"kind": "none"}}}, 404, None, 2))  # fmt: skip
            if slug == "cash":
                cases.append(("paid from another user's account", "POST", "/api/assets/other",
                              {"json": {**other_body, "paid_from": {"cash_id": item.id}}}, 422, CASH_ACCOUNT_ERROR, 2))  # fmt: skip
        for ex in self.exits.values():
            cases.append((f"undo {ex.kind}", "DELETE", f"/api/exits/{ex.id}", {}, 404, None, 2))
            for cid in self.u2cash:  # the second user's own account, the first user's exit
                cases.append(("reinvest from another user's exit", "POST", "/api/assets/other",
                              {"json": {**other_body, "paid_from": {"cash_id": cid, "from_exit_id": ex.id}}}, 422, CASH_ACCOUNT_ERROR, 2))  # fmt: skip
                break
        for sip in self.sips.values():
            base = f"/api/sips/{sip.id}"
            cases += [
                ("sip pause", "POST", base + "/pause", {}, 404, None, 2),
                ("sip resume", "POST", base + "/resume", {}, 404, None, 2),
                ("sip stop", "POST", base + "/stop", {}, 404, None, 2),
                ("sip skip", "POST", base + "/skip", {}, 404, None, 2),
                ("sip unskip", "DELETE", base + "/skip/2026-04-05", {}, 404, None, 2),
                ("sip put", "PUT", base, {"json": {"amount": 500, "day_of_month": 5}}, 404, None, 2),
                ("sip delete", "DELETE", base, {}, 404, None, 2),
            ]  # fmt: skip
        for fund in self.holds_of("mf"):
            body = {"scheme_code": SCHEME, "platform": "Groww", "amount": 500, "day_of_month": 5,
                    "start_date": "2026-03-01", "include_past": False, "mutual_fund_id": fund.id}  # fmt: skip
            cases.append(("sip create on another user's fund", "POST", "/api/sips", {"json": body}, 404, None, 2))
        # the other direction: user 1 with the second user's ids
        for slug, hid, _inv, _qty in self.u2hold:
            base = f"/api/assets/{slug}/{hid}"
            cases += [
                (f"user 1 get {slug}", "GET", base, {}, 404, None, 1),
                (f"user 1 delete {slug}", "DELETE", base, {}, 404, None, 1),
                (f"user 1 detail {slug}", "GET", f"/api/holdings/{slug}/{hid}", {}, 404, None, 1),
            ]  # fmt: skip
        for slug, hid, _inv, qty in self.u2hold:
            if slug == "stock" and self.live_cash():  # the second user's stock sold into user 1's account
                cash = self.live_cash()[0]
                body = {**sale, "quantity": 1, "destination": {"kind": "cash_existing", "cash_id": cash.id}}
                cases.append(("sell into another user's account", "POST", f"/api/holdings/stock/{hid}/sell",
                              {"json": body}, 422, CASH_ACCOUNT_ERROR, 2))  # fmt: skip
                break
        if not cases:
            return
        # first a kind of call, then one of its targets (a flat draw over all cases favours the first items)
        label = data.draw(st.sampled_from(sorted({c[0] for c in cases})))
        label, method, url, kwargs, want, prefix, who = data.draw(st.sampled_from([c for c in cases if c[0] == label]))
        kwargs = dict(kwargs)
        if kwargs.pop("put", False):
            got = self.h.call("GET", url)
            if got.status_code != 200:
                self.fail(f"cross user: GET {url} -> {got.status_code}")
            from app.routers.assets import REGISTRY

            slug = url.split("/")[3]
            kwargs["json"] = {k: v for k, v in got.json().items() if k in REGISTRY[slug][1].model_fields}
        before = self.h.snapshot()
        r = self.h.call(method, url, as_user=who, **kwargs)
        self.expect(r, (want,), f"cross-user {label}", prefix)
        if self.h.snapshot() != before:
            self.fail(f"cross-user {label} ({r.status_code}) changed the database")

    # ---- market data (optional steps; values differ from invested once they exist) -------------
    # Each rule writes the latest row AND the history row for the same day, like the nightly
    # imports, so latest and history never disagree. Known drifts (a stock with a latest price but
    # no history close; gold carried past 7 days) are pinned in tests/test_networth_today_agreement.py
    # and cannot be seen here anyway: the history's last point is overwritten by the dashboard total.
    @rule(data=st.data())
    def set_stock_price(self, data):
        master = data.draw(st.sampled_from(self.h.stock_masters))
        price = from_cents(data.draw(st.integers(100, 500_000)))
        prev = from_cents(data.draw(st.integers(100, 500_000)))
        self.h.set_stock_price(master, price, prev)
        TALLY["market stock price"] += 1

    @rule(data=st.data())
    def set_mf_nav(self, data):
        lag = data.draw(st.sampled_from([0, 0, 0, 1, 3]))  # a weekend or holiday lag
        self.h.set_mf_latest_nav(self.h.today - timedelta(days=lag))
        TALLY["market mf nav"] += 1

    @rule(data=st.data())
    def set_nps_nav(self, data):
        scheme = data.draw(st.sampled_from(self.h.nps_schemes))
        nav = from_cents(data.draw(st.integers(1_000, 20_000))).quantize(Decimal("0.0001"))
        self.h.set_nps_nav(scheme, nav, self.h.today - timedelta(days=data.draw(st.sampled_from([0, 0, 1, 3]))))
        TALLY["market nps nav"] += 1

    @rule(data=st.data())
    def set_metal_rate(self, data):
        metal = data.draw(st.sampled_from(["gold", "silver"]))
        rate = from_cents(data.draw(st.integers(500, 1_500_000)))
        # Days without a rate: the rate may be dated up to 20 days back (never before the last one),
        # and most days have no rate at all (the clock moves without this rule running).
        age = data.draw(st.sampled_from([0, 0, 1, 3, 8, 20]))
        rate_date = max(self.h.today - timedelta(days=age), self.rate_dates.get((metal, "999"), date.min))
        self.h.set_metal_rate(metal, "999", rate, rate_date)
        self.rate_dates[(metal, "999")] = rate_date
        TALLY["market metal rate"] += 1

    def teardown(self) -> None:
        from tests.stateful import reads

        if hasattr(self, "holds"):
            reads.check_reads(self, force=True)

    # ---- invariants ---------------------------------------------------------------------------
    @invariant()
    def check(self) -> None:
        if not hasattr(self, "holds"):  # before __init__ finished
            return
        self.refresh_mf()
        h = self.h
        # cash: the model's balance is the app's balance, for every account
        u = h.uid  # user 2's rows are in the same tables: every comparison below is user 1's only
        rows = {r.id: r for r in h.rows("SELECT id, balance, deleted_at FROM cash_holdings WHERE user_id = :u", u=u)}
        if set(rows) != set(self.cash):
            self.fail(f"cash accounts differ: app {sorted(rows)} model {sorted(self.cash)}")
        for cid, c in self.cash.items():
            r = rows[cid]
            if q2(r.balance) != c.bal:
                self.fail(f"cash {cid} ({c.name}): app balance {q2(r.balance)} != model {c.bal}")
            if (r.deleted_at is None) != c.live:
                self.fail(f"cash {cid}: deleted flag differs (app live={r.deleted_at is None})")
            if c.bal < 0:
                self.fail(f"cash {cid} negative in the model")
        if h.scalar("SELECT count(*) FROM cash_holdings WHERE balance < 0"):
            self.fail("negative cash balance in the app")

        # holdings
        deleted: dict[tuple[str, int], bool] = {}
        for slug in ("fd", "rd", "stock", "bond", "mf", "nps", "gold", "pf", "other"):
            ids = {}
            for r in h.rows(f"SELECT id, deleted_at FROM {TABLES[slug]} WHERE user_id = :u", u=u):  # noqa: S608
                ids[r.id] = r.deleted_at is not None
                deleted[(slug, r.id)] = r.deleted_at is not None
            known = {k[1] for k in self.holds if k[0] == slug}
            if set(ids) != known:
                self.fail(f"{slug} rows differ: app {sorted(ids)} model {sorted(known)}")
        for hold in self.holds.values():
            if deleted[hold.key] == hold.live:
                self.fail(f"{hold.key}: live flag differs (app deleted={deleted[hold.key]})")
            if hold.slug in SELLABLE:
                qty, invested, closed = self.db_state(hold)
                if closed != hold.closed:
                    self.fail(f"{hold.key}: closed differs (app {closed}, model {hold.closed})")
                if hold.slug in ("stock", "bond", "gold", "mf") and qty != hold.qty:
                    self.fail(f"{hold.key}: quantity {qty} != model {hold.qty}")
                if hold.slug in ("bond", "gold", "other", "mf") and invested != hold.invested:
                    self.fail(f"{hold.key}: invested {invested} != model {hold.invested}")

        # exits and fundings: exactly the model's, no orphans, funding active exactly while live
        exit_rows = h.rows(
            "SELECT id, asset_type, holding_id, kind, cash_holding_id, cash_added, amount, cost "
            "FROM holding_exits WHERE user_id = :u", u=u,
        )  # fmt: skip
        if {r.id for r in exit_rows} != set(self.exits):
            self.fail(f"exits differ: app {sorted(r.id for r in exit_rows)} model {sorted(self.exits)}")
        for r in exit_rows:
            ex = self.exits[r.id]
            if (r.asset_type, r.holding_id) not in deleted:
                self.fail(f"orphaned exit {r.id}")
            if (r.asset_type, r.holding_id, r.kind, r.cash_holding_id) != (ex.slug, ex.hid, ex.kind, ex.cash_id):
                self.fail(f"exit {r.id} differs from the model")
            if q2(r.cash_added or 0) != ex.added or q2(r.amount) != ex.amount:
                self.fail(f"exit {r.id}: money differs (app {r.cash_added}/{r.amount}, model {ex.added}/{ex.amount})")
        if h.scalar(
            "SELECT count(*) FROM (SELECT asset_type, holding_id FROM holding_exits "
            "WHERE kind = 'maturity' GROUP BY asset_type, holding_id HAVING count(*) > 1) x"
        ):
            self.fail("a holding was settled twice")
        fund_rows = h.rows(
            "SELECT asset_type, holding_id, cash_holding_id, amount, refunded_at, from_exit_id "
            "FROM holding_fundings WHERE user_id = :u", u=u,
        )  # fmt: skip
        for r in fund_rows:
            if (r.asset_type, r.holding_id) not in deleted:
                self.fail(f"orphaned funding on {r.asset_type} {r.holding_id}")
            if (r.refunded_at is None) == deleted[(r.asset_type, r.holding_id)]:
                self.fail(f"funding on {r.asset_type} {r.holding_id}: refunded_at={r.refunded_at} but deleted={deleted[(r.asset_type, r.holding_id)]}")
        app_f = sorted((r.asset_type, r.holding_id, r.cash_holding_id or 0, q2(r.amount), r.refunded_at is None, r.from_exit_id or 0) for r in fund_rows)
        model_f = sorted(
            (hold.slug, hold.id, f.cash_id or 0, f.amount, f.active, f.from_exit or 0)
            for hold in self.holds.values() for f in hold.fundings
        )
        if app_f != model_f:
            self.fail(f"fundings differ:\n app   {app_f}\n model {model_f}")

        # secondary check: the row-derived ledger (skipped for accounts edited by hand)
        for cid, c in self.cash.items():
            if c.put:
                continue
            added = sum((q2(r.cash_added) for r in exit_rows if r.cash_holding_id == cid and r.cash_added is not None), ZERO)
            taken = sum((q2(r.amount) for r in fund_rows if r.cash_holding_id == cid and r.refunded_at is None), ZERO)
            if c.initial + added - taken != q2(rows[cid].balance):
                self.fail(f"cash {cid}: ledger {c.initial} + {added} - {taken} != app {q2(rows[cid].balance)}")

        # funds: units vs transactions, closed_on, SIP links
        txns: dict[int, list] = {}
        for r in h.rows(
            "SELECT t.id, t.mutual_fund_id, t.kind, t.units, t.amount, t.txn_date, t.sip_id, t.manual FROM mf_transactions t "
            "JOIN mutual_funds f ON f.id = t.mutual_fund_id WHERE f.user_id = :u", u=u,
        ):  # fmt: skip
            txns.setdefault(r.mutual_fund_id, []).append(r)
        fund_state = {
            r.id: r for r in h.rows(
                "SELECT id, units, invested_amount, closed_on, deleted_at FROM mutual_funds WHERE user_id = :u", u=u
            )
        }  # fmt: skip
        for fid, ts in txns.items():
            if fid not in fund_state:
                self.fail(f"transactions of a missing fund {fid}")
            f = fund_state[fid]
            if f.deleted_at is None and f.closed_on is None:
                net = sum((q3(t.units) if t.kind == "purchase" else -q3(t.units) for t in ts), ZERO)
                if net != q3(f.units):
                    self.fail(f"fund {fid}: units {q3(f.units)} != net transactions {net}")
            if f.closed_on is not None:
                late = [t for t in ts if t.kind == "purchase" and t.txn_date > f.closed_on]
                if late:
                    self.fail(f"fund {fid} closed on {f.closed_on} has a purchase dated {late[0].txn_date}")
        if h.scalar(
            "SELECT count(*) FROM mf_transactions t LEFT JOIN mutual_funds f ON f.id = t.mutual_fund_id "
            "WHERE f.id IS NULL"
        ):
            self.fail("a transaction of a fund that no longer exists (purge must take them along)")
        sip_rows = h.rows("SELECT id, mutual_fund_id, status FROM mf_sips WHERE user_id = :u", u=u)
        if {s.id for s in sip_rows} != set(self.sips):
            self.fail(f"SIPs differ: app {sorted(s.id for s in sip_rows)} model {sorted(self.sips)}")
        for s in sip_rows:
            if s.mutual_fund_id is not None and s.mutual_fund_id not in fund_state:
                self.fail(f"SIP {s.id} points at a missing fund {s.mutual_fund_id}")
            if s.id in self.sips and s.status != self.sips[s.id].status:
                self.fail(f"SIP {s.id}: status {s.status} != model {self.sips[s.id].status}")

        # partly sold holdings keep a cost floor; fully sold ones sum to what was invested
        sales: dict[tuple[str, int], list] = {}
        for r in exit_rows:
            if r.kind == "sale":
                sales.setdefault((r.asset_type, r.holding_id), []).append(r)
        for key, rs in sales.items():
            hold = self.holds[key]
            if not hold.live and not hold.closed:
                continue
            total = sum((q2(r.cost) for r in rs), ZERO)
            if hold.closed:
                if hold.slug == "mf":
                    # the machine's own basis ledger: a fund with a sale can't be edited, so what was
                    # invested before its first sale plus the amounts of the SIP and Buy more (manual)
                    # purchase rows posted after it. "After" is row order: ids grow with insertion, and
                    # the first live sale's redemption row (no sip_id) marks the point (dates and
                    # timestamps can tie).
                    exs = [self.exits[r.id] for r in sorted(rs, key=lambda r: r.id)]
                    ts = txns.get(hold.id)
                    redemptions = [t.id for t in ts or [] if t.kind == "redemption" and t.sip_id is None]
                    if not redemptions:
                        self.fail(f"{key}: a live sale but no redemption transaction")
                    mark = min(redemptions)
                    sip_after = sum(
                        (
                            q2(t.amount) for t in ts
                            if t.kind == "purchase" and (t.sip_id is not None or t.manual) and t.id > mark
                        ),
                        ZERO,
                    )
                    expect_total = exs[0].pre[1] + sip_after
                    if ts and not hold.cost_edited:
                        bought = sum((q2(t.amount) for t in ts if t.kind == "purchase"), ZERO)
                        if total != bought:
                            self.fail(f"{key}: sale costs {total} != purchases {bought}")
                else:
                    expect_total = hold.invested0
                if expect_total is not None and total != expect_total:
                    self.fail(f"{key}: sale costs {total} != invested {expect_total}")
            elif hold.slug in ("bond", "gold", "mf") and hold.invested < floor_of(hold.slug, hold.qty):
                self.fail(f"{key}: invested {hold.invested} below the floor for {hold.qty} left")

        # GET then PUT of the same body for the holding this step touched
        if self.touched is not None:
            key, self.touched = self.touched, None
            self.roundtrip(key)

        # the read side: dashboard, portfolio, net worth and the grids agree with the model
        from tests.stateful import reads

        reads.check_reads(self)

    def roundtrip(self, key: tuple[str, int]) -> None:
        from app.routers.assets import REGISTRY

        hold = self.holds.get(key)
        if hold is None or not hold.live:
            return
        slug = hold.slug
        got = self.h.call("GET", f"/api/assets/{slug}/{hold.id}")
        if got.status_code != 200:
            self.fail(f"GET {slug} {hold.id} -> {got.status_code}")
        fields = REGISTRY[slug][1].model_fields
        body = {k: v for k, v in got.json().items() if k in fields}
        r = self.h.call("PUT", f"/api/assets/{slug}/{hold.id}", json=body)
        want = 409 if (hold.closed or hold.settled) else 200
        if r.status_code != want:
            self.fail(f"GET then PUT of the same body for {key}: expected {want}, got {r.status_code}: {r.text[:300]}")

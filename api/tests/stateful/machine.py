"""The money-conservation state machine (shared by the SQLite and the Postgres test).

The machine drives the HTTP API (assets, exits, SIPs) and keeps its OWN model of the world: the
expected balance of every cash account, and for every holding whether it is live, deleted or closed,
its quantity and invested amount, its exits and its fundings. The model is updated ONLY from
2xx responses. Every rule PREDICTS the outcome from the model and requires exactly that status
(or, where the model cannot know, a fixed small set), so a wrong 4xx fails as surely as a 5xx.

Cash semantics modelled (the "ideal" ledger): a cash account's balance is always
initial + exit proceeds paid into it - active fundings paid from it (reset by a PUT), whether or not
the account is soft-deleted. Deleting a holding refunds its funding, restoring it debits it again
(409 when short, also for a deleted account). A holding with a sale or settlement can't be deleted.

Invariants after EVERY step: no 5xx; app balance == model balance for every cash account (live or
deleted); no negative cash; the exits and fundings in the database are exactly the model's; no
orphan exit or funding; a funding is active exactly while its holding is live; no double settlement;
a live fund's units equal its net transactions; no dangling SIP link; no purchase transaction
dated after a fund's closed_on; SIP posting never touches a closed or deleted fund; a partly sold
holding keeps invested >= remainder floor; sale costs of a fully sold holding sum to what was
invested; sell-then-undo restores quantity/units/weight, invested and closed_on exactly; GET then
PUT of the same body returns 200 (409 for a closed holding); the row-derived ledger formula
(initial + exits - fundings) as a secondary check.

Known limits (documented, see test_money_machine.py): no concurrency (tests/pg covers it), no
purge, SQLite does not enforce foreign keys (ON DELETE actions only run on Postgres).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import ROUND_UP, Decimal

import hypothesis.strategies as st
from hypothesis import event
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from tests.stateful.world import (
    LAST_TODAY, SCHEME, START_TODAY, Harness, d, from_cents, from_milli, q2, q3, reason, sx,
)  # fmt: skip

SELLABLE = ("stock", "bond", "mf", "gold", "other")
ADD_SLUGS = ("fd", "stock", "bond", "mf", "gold", "other")
TABLES = {
    "fd": "fixed_deposits", "stock": "stocks", "bond": "bonds", "mf": "mutual_funds",
    "gold": "gold_holdings", "other": "other_holdings", "cash": "cash_holdings",
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


@dataclass
class FundM:
    cash_id: int
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
    closed: bool = False  # sold in full (closed_on set)
    settled: bool = False
    invested0: Decimal = ZERO
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
    # Rules named here are left out (a known bug excluded until it is fixed, see test_known_bugs).
    excluded_rules: frozenset[str] = frozenset()

    def __init__(self, harness: Harness) -> None:
        super().__init__()
        self.h = harness
        harness.reset()  # also asserts the engine is a test database
        self.cash: dict[int, CashM] = {}
        self.holds: dict[tuple[str, int], HM] = {}
        self.exits: dict[int, ExitM] = {}
        self.gone: list[int] = []  # exit ids that were undone
        self.sips: dict[int, SipM] = {}
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
        slug = data.draw(st.sampled_from(ADD_SLUGS))
        mode = data.draw(st.sampled_from(["none", "none", "paid", "paid", "paid", "edge", "dead"]))
        pool = self.dead_cash() if mode == "dead" else self.live_cash()
        cash = data.draw(st.sampled_from(pool)) if pool and mode != "none" else None
        forced = None
        if cash is not None and mode in ("paid", "edge"):
            bal = int(cash.bal * 100)
            if mode == "edge" and bal > 0:
                forced = data.draw(st.sampled_from([bal, bal + 1]))
            elif bal > 0:
                forced = data.draw(st.integers(1, bal)) if data.draw(st.booleans()) else None
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

    # ---- sell ---------------------------------------------------------------------------------
    def pick_dest(self, data):
        kind = data.draw(st.sampled_from(["none", "none", "existing", "existing", "dead", "new"]))
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
                allowed = (201, 422)  # FIFO cost is the app's: only a refusal with its message
            else:
                cost = q2(invested * qty / held)
                if q2(invested - cost) < CENT:
                    allowed, prefix = (422,), REFUSED
        if slug != "mf" and allowed == (201,) and not full and cost is None:
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
        self.touched = hold.key
        if repeat and full:
            self.resend(f"sell {slug}", "POST", f"/api/holdings/{slug}/{hold.id}/sell", (409,), json=body)

    # ---- settle -------------------------------------------------------------------------------
    @precondition(lambda self: bool(self.holds_of("fd", "bond")))
    @rule(data=st.data())
    def settle(self, data):
        self.do_settle(data, repeat=False)

    @precondition(lambda self: bool(self.holds_of("fd", "bond")))
    @rule(data=st.data())
    def settle_twice(self, data):
        """Double submit: a settlement, then the same request again (409: already settled)."""
        self.do_settle(data, repeat=True)

    def do_settle(self, data, repeat: bool):
        good = [h for h in self.holds_of("fd", "bond", live=True) if h.matured and not h.settled]
        hold = self.choose(data, good, self.holds_of("fd", "bond"))
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

    def do_undo(self, data, repeat: bool):
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

    def do_delete(self, data, repeat: bool):
        items = self.items()
        # Mostly holdings that can be deleted (no sale or settlement on record), sometimes any.
        free = [i for i in items if i.live and not (isinstance(i, HM) and i.exits)]
        with_exits = [i for i in items if i.live and isinstance(i, HM) and i.exits]
        if with_exits and not repeat and data.draw(st.sampled_from([False, True, True])):
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
        item.live = False
        for f in getattr(item, "fundings", []):
            if f.active:  # the ideal ledger: the refund goes back whether or not the account is deleted
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
                if not f.active:
                    if bal[f.cash_id] < f.amount:
                        want, prefix = (409,), "Not enough in"
                        break
                    bal[f.cash_id] -= f.amount
        r = self.h.call("POST", f"/api/assets/{slug}/{item.id}/restore")
        if self.expect(r, want, f"restore {slug}", prefix) >= 400:
            return
        item.live = True
        for f in getattr(item, "fundings", []):
            if not f.active:
                self.cash[f.cash_id].bal -= f.amount
                f.active = True
        self.touched = item.key if isinstance(item, HM) else None
        if repeat:
            self.resend(f"restore {slug}", "POST", f"/api/assets/{slug}/{item.id}/restore", (404,))

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
        slug = data.draw(st.sampled_from(["cash", "fd", "stock", "bond", "other"]))
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

    # ---- the second user -----------------------------------------------------------------------
    @precondition(lambda self: len(self.u2cash) + len(self.u2hold) < 6)
    @rule(data=st.data())
    def u2_add(self, data):
        """The second user adds a cash account, an Other holding (with an amount invested) or a stock."""
        kind = data.draw(st.sampled_from(["cash", "other", "stock", "stock"]))
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
        elif kind == "other":
            self.u2hold.append(("other", new, from_cents(cents), None))
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
            if slug in ("fd", "bond"):
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
        for slug in ("fd", "stock", "bond", "mf", "gold", "other"):
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
        app_f = sorted((r.asset_type, r.holding_id, r.cash_holding_id, q2(r.amount), r.refunded_at is None, r.from_exit_id or 0) for r in fund_rows)
        model_f = sorted(
            (hold.slug, hold.id, f.cash_id, f.amount, f.active, f.from_exit or 0)
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
            "SELECT t.mutual_fund_id, t.kind, t.units, t.amount, t.txn_date FROM mf_transactions t "
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
                    ts = txns.get(hold.id)
                    expect_total = sum((q2(t.amount) for t in ts if t.kind == "purchase"), ZERO) if ts else None
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

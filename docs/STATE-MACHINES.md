# Implicit state machines

Inventory of lifecycles that are not one status field but are inferred from several columns, flags and rows. Built from the code at HEAD (after commit 61050df); the code wins over SPEC/AGENTS where they differ. All paths are under `api/` (`app/...`, `tests/...`, `scripts/...`). "Unverified" means I did not confirm enforcement; the item names what to check.

Legend for the "prevented by" columns: CHECK = DB CHECK constraint, UQ = DB unique/partial unique index, FK = foreign key action, API = guard in a router or service, INV = nightly `scripts/invariants.sql`, MACHINE = Hypothesis money machine (`tests/stateful/machine.py`), TEST = a named deterministic/unit test, none = unguarded.

Global mechanics all lifecycles share:
- Soft-delete filter: every ORM SELECT on a `TimestampedMixin` model gets `deleted_at IS NULL` unless `include_deleted=True` (`app/models/base.py`, `_exclude_soft_deleted` event at the end of the file). Core/raw SQL is not covered.
- Writers (`record_sale`, `record_settlement`, `undo_exit`, `fundings.*`) never commit; the router commits once (`app/services/exits.py:3-5`, `app/services/fundings.py:1-7`).
- Row locks: holding `FOR UPDATE OF model`; undo locks exit, holding, cash; reinvest locks exit, cash; refund/restore lock holding, fundings, cash; purge locks holdings by type, exits/fundings pointing at purgeable cash, then cash (`app/services/purge.py:45-56,143-156`).

---

## 1. Holding (ten types)

Types and what they can do: sell (closed_on + `sale` exits): stock, bond, mf, gold, other. Settle (`maturity` exit): fd, rd, bond. No exits at all: nps, cash, pf. `holding_exits.asset_type` enum is only fd, rd, bond, stock, mf, gold, other (`app/models/holding_exit.py:46-48`). `closed_on` exists only on stock, bond, mf, gold, other (migration 0029; `app/models/{stock,bond,mutual_fund,gold,other}.py`).

### 1a. States

| State | How it is represented |
|---|---|
| Live, untouched | `deleted_at IS NULL`, `closed_on IS NULL` (where the column exists), no `holding_exits` row for (asset_type, holding_id) |
| Matured (derived, not stored) | fd/rd/bond: today past maturity date; computed by `holding_status` (`app/services/exits.py:295-303`, via `valuation._status`). Not a column |
| Sold in part | live, `closed_on IS NULL`, at least one `kind='sale'` exit with `prev_state.full` absent/false (`exits.py:744-751` `_was_full_sale`); quantity/invested reduced (`exits.py:631-646`) |
| Sold in full ("closed") | `closed_on = sale date` AND a `sale` exit with `prev_state.full = true`; quantity and invested are NOT reduced (`exits.py:609`, docstring `exits.py:7-9`); grid status forced to "sold" (`app/routers/portfolio.py:134-136`) |
| Settled | a `kind='maturity'` exit exists (at most one: UQ `uq_holding_exits_maturity`, `app/models/holding_exit.py:23-30`). `closed_on` stays NULL (INV `closed_without_sale` comment) |
| Soft-deleted | `deleted_at IS NOT NULL` (set by `func.now()`, `app/routers/assets.py:314`) |
| Purged | row gone; its exits, fundings and (via FK CASCADE) mf_transactions gone (`app/services/purge.py:158-187`) |
| Closed tab membership | derived in `app/routers/holdings.py:131-201` from `closed_on`, the latest exit, `settled`, `maturity_date` |

Derived data on grid items: `exit` (latest exit summary) and `settled` come from `fetch_exit_info` (`exits.py:414-426`); `paid_from` from `fundings.paid_from_info` (`fundings.py:366-393`).

### 1b. Transitions

| From -> To | Trigger | Guards (file:line) | Side effects |
|---|---|---|---|
| (none) -> live | `POST /api/assets/{slug}` | duplicate 409 unless `confirm_duplicate` (`routers/assets.py:174-180`); `paid_from` plan checks (`routers/assets.py:159-173`, `fundings.py:107-141`) | optional funding row + cash debit (`assets.py:184-187`); NPS history sync scheduled (`assets.py:190-191`) |
| live -> live (edit) | `PUT /api/assets/{slug}/{id}` | row locked `assets.py:210-214`; 409 if `closed_on` set or a `maturity` exit exists (`assets.py:227-235`); 422 on changed SOLD_IN_PART_FIELDS when any `sale` exit exists (`assets.py:236-249`, field list `app/schemas/assets.py:641-647`); funding plan 422s (`fundings.py:243-264`) | cost edit of fd/stock/bond/mf/gold/other moves the difference on the funding account (`assets.py:267-268`, `fundings.py:269-275`) |
| live -> sold in part | `POST /api/holdings/{slug}/{id}/sell` (partial) | holding locked `routers/exits.py:133`; `_not_active`: already sold / matured bond (`exits.py:325-340,560-562`); `check_sale` date/qty/price/charges (`exits.py:253-290`); `check_remainder` blocks leaving less than the floor (`exits.py:234-241,605`); cash destination must be the user's live account (`exits.py:511-520`) | quantity/invested reduced; MF: redemption `mf_transactions` row (and opening purchase if none) (`exits.py:577-590,648-657`); exit row with `prev_state`; optional cash credit (`exits.py:523-553`) |
| live / sold in part -> sold in full | sell with quantity = all held | same as above, `plan.full` | `closed_on = sale date` (`exits.py:609`); quantity and invested kept; MF redemption row |
| matured (fd, rd, bond) -> settled | `POST .../settle` | `closed_on` set -> 409 (`exits.py:675-678`); not matured -> 409 (`exits.py:679-683`); already settled -> 409 (`exits.py:684-693`) plus UQ catch (`routers/exits.py:195-205`); date not future / not before maturity (`exits.py:697-700`) | exit row, cost = item invested; optional cash credit |
| sold in part / sold in full / settled -> previous | `DELETE /api/exits/{id}` (undo) | exit row locked (`routers/exits.py:238-242`); holding missing/deleted -> 409 (`:245-257`); not the latest exit of that holding -> 409 (`:258-265`); some money reinvested (active funding with `from_exit_id`) -> 409 (`:267-274`); cash short -> 409 (`exits.py:764-784`) | full sale: `closed_on = NULL` (`exits.py:786`); partial: add back sold quantity and cost (`exits.py:787-803`); legacy `stopped_sips` -> paused (`exits.py:807-816`); delete redemption txn (`exits.py:817-818`); debit cash by `cash_added`, restore balance date (`exits.py:820-833`); delete exit row |
| live -> soft-deleted | `DELETE /api/assets/{slug}/{id}` | row locked, 404 if already deleted (`assets.py:286-292`); any exit row (sale or maturity) -> 409 (`assets.py:294-311`) | `deleted_at` set; active fundings refunded to their account, active or soft-deleted (`assets.py:314-315`, `fundings.py:308-315`) |
| soft-deleted -> live | `POST .../restore` | locked, must still be deleted else 404 (`assets.py:326-334`); funding re-debit must fit the balance else 409 (`fundings.py:318-338`, `assets.py:335-342`) | `refunded_at` cleared, account debited; NPS sync rescheduled |
| soft-deleted -> purged | `/api/cron/purge`, `python -m app.jobs.purge_deleted` | `deleted_at < now - 30 days` re-evaluated under lock (`purge.py:73-88`); lock timeout 10 s -> `PurgeLockTimeout` -> 503 (`purge.py:50-66`, `routers/cron.py:99-104`) | delete exits and fundings of the holding (`purge.py:164-174`), the row; FK SET NULL on SIP `mutual_fund_id`, funding/exit `cash_holding_id` |
| MF live -> MF updated | `POST /api/import/cas/commit` row `action=update` | refused (422) when any exit exists for the fund (`routers/cas_import.py:97-99,126-128,137-138`; `services/cas_import.py:246-263`); holding locked (`:99-106,130-134`) | units/avg_nav/invested/purchase_date overwritten, transactions replaced except later SIP rows and later manual (Buy more) rows (`services/cas_import.py:281-318`) |
| MF live / sold in part -> MF + buy | `POST /api/holdings/mf/{id}/buy` (SPEC §8d) | fund locked (`FOR UPDATE OF`, `populate_existing`, `routers/buys.py`); `_not_active` (sold in full -> 409); date not future, not before `purchase_date`, not before the latest sale (sale exits and redemption rows) -> 422; units > 0 and <= 1 crore; same manual buy (date, amount, units) -> 409 unless `confirm_duplicate`; mf only, else 404 (`services/buys.py` `record_mf_buy`) | opening purchase if no transactions; `mf_transactions` purchase row (`sip_id` NULL, `manual` true); units, invested, avg_nav raised; `purchase_date` kept; no cash moves |
| MF + buy -> MF (undo buy) | `DELETE /api/holdings/mf/{id}/buys/{txn_id}` | fund locked; row must be a manual purchase of this fund else 404; `undo_refusal`: sold in full -> 409; a sale or redemption dated on or after the buy (same day included) -> 409; units left <= 0 or invested below `remainder_floor('mf', left)` -> 409 (`services/buys.py`) | row deleted; units, invested subtracted, avg_nav recomputed; `purchase_date` kept. `undoable` on the transactions list uses the same rule |
| MF live -> MF + instalment | SIP posting (`post_due`) | holding must be live and open; see lifecycle 4 | units, invested, avg_nav, `last_posted_on` updated (`services/sip.py:365-373`) |

### 1c. Illegal combinations

| Illegal combination | Prevented by |
|---|---|
| Soft-deleted AND has any exit | API 409 on delete (`assets.py:303-311`); MACHINE rule delete + `test_known_bugs.py:130-175`. INV: none (see gaps) |
| `closed_on` set without a `sale` exit | INV `closed_without_sale`; MACHINE |
| `closed_on` set AND a `maturity` exit | API: settle refuses (`exits.py:675`), sell refuses matured bonds (`exits.py:331-335`). INV/CHECK: none |
| Two `maturity` exits for one holding | UQ `uq_holding_exits_maturity`; INV `duplicate_settlement`; API 409 |
| Sale after `closed_on` (second full sale) | API `_not_active` (`exits.py:560`); INV: none; MACHINE sell_twice |
| Full-sale cost != invested | INV `sale_cost_vs_invested` (stock within 0.01) |
| Quantity/units/weight <= 0, invested < 0 | CHECK per model (`ck_*_positive`, `ck_*_nonnegative`; migration 0032, test `tests/test_migration_0032.py`, `tests/test_db_constraints.py`) |
| Exit quantity <= 0, amount/cost/charges < 0 | CHECK `ck_holding_exits_*` (`holding_exit.py:31-36`) |
| Sale/settle exit on a type that cannot have it (nps, cash, pf) | CHECK on `asset_type` enum; API `SELL_TYPES`/`SETTLE_TYPES` (`routers/exits.py:131-132,177-178`). `sale` on fd/rd and `maturity` on stock/mf/gold/other pass the enum, prevented by API only |
| Exit/funding row whose holding row is gone | INV `orphan_exit`, `orphan_funding` (no FK by design) |
| Live MF with transactions whose units != net | INV `mf_units_vs_transactions` (only open live funds); MACHINE |
| Buy dated before the fund's purchase date or latest sale | API 422 (`services/buys.py`); MACHINE buy_more; TEST `tests/test_buy_more.py` |
| Undo of a buy a later or same-day sale may have used | API 409 `undo_refusal`; MACHINE undo_buy (also right after a sell the same day); TEST `tests/pg/test_buy_more_pg.py` |
| Partly sold holding edited in sold-in-part fields | API `assets.py:236-249`; TEST `tests/test_edit_guards.py` |
| Edit of closed or settled holding | API `assets.py:227-235`; TEST `tests/test_edit_guards.py`; MACHINE (GET then PUT roundtrip) |

### 1d. Duplicated guards

| Rule | Places |
|---|---|
| "No edit once closed/settled; sold-in-part field list" | `routers/assets.py:227-249`; web `lib/edit-guards.ts` (checked against `schemas/assets.py` by `tests/test_edit_guards.py`) |
| "Cannot delete a holding with an exit" | `routers/assets.py:294-311`; web `lib/delete-guard.ts`; wording in `schemas/exits.py` |
| "Sold/matured means no more selling" | `exits.py:325-340` (`_not_active`), `exits.py:675-683` (settle), `routers/portfolio.py:134`, `services/networth.py:85-89`, `services/duplicates.py:90-97`, `services/sip.py:245,294`, `routers/sips.py:148,156` (each re-derives "sold" from `closed_on`, not from exit rows) |
| "Has sale or settlement" (exit rows) | `assets.py:218-226` (PUT), `assets.py:294-302` (DELETE), `services/cas_import.py:246-263` (CAS; any kind, MF only), `routers/exits.py:258` (latest), `exits.py:414-426` (grid info) |
| "Full sale" | `prev_state.full` flag with fallback `closed_on == exit_date` (`exits.py:744-751`) |
| Status "matured" | `valuation._status` used by `holding_status`; the settle router uses the valued grid item's status (`exits.py:679`), so two routes compute it |
| Soft-deleted filter | ORM event (`base.py`), raw SQL repeats `deleted_at IS NULL` in `services/nav_history.py:209-214,271-278` |

### 1e. Gaps

- INV has no query for "soft-deleted holding with an exit" or "`closed_on` and `maturity` exit together" or "second sale after a full sale".
- `holding_status` "matured" for a partly sold bond (sell refused, settle allowed): behaviour of settle on a partly sold bond is unverified (check `item.invested` in `record_settlement` at `exits.py:711`, and MACHINE coverage of partial sale then maturity).
- MACHINE does not exercise CAS import (`/api/import/cas/commit`) or the sold-in-part field edits (only roundtrip PUT). CAS guards covered by `tests/test_cas_import_guards.py` only.
- NPS, cash, pf have no exit lifecycle; MACHINE covers nps, pf edits and cash puts.
- Legacy `prev_state.stopped_sips` (`exits.py:807-816`) is read but no code writes it (grep in `app/`): dead path kept for old exit rows; untested by MACHINE.
- Undo with the cash account purged: `cash is None` skips the debit silently (`exits.py:764-784`); money is no longer tracked. By design per `fundings.py:255` comment for edits; for undo, check SPEC §8b wording (unverified).

---

## 2. Funding (`holding_fundings`)

### 2a. States

| State | Representation |
|---|---|
| Active | `refunded_at IS NULL`; at most one per (asset_type, holding_id): UQ `uq_holding_fundings_active` (`holding_funding.py:27-35`) |
| Refunded (history) | `refunded_at` set; row kept; money returned to the account |
| Account purged ("gone") | `cash_holding_id IS NULL` (FK ON DELETE SET NULL, `holding_funding.py:46-48`); active or refunded |
| Account soft-deleted | cash row `deleted_at` set; funding still links to it; still debited/credited (`fundings.py:278-288` uses `include_deleted`) |
| Reinvest | `from_exit_id` set (FK SET NULL); exit counts the money as reinvested while the funding is active (`fundings.py:341-356`) |
| In sync / out of sync | derived, not stored: stored cost == `funding.amount` (`fundings.py:250,425-429`) |
| Adjustable | derived in `paid_from_info`: type in EDIT_ADJUSTS and account exists and not deleted (`fundings.py:389,396-402`) |

### 2b. Transitions

| From -> To | Trigger | Guards | Side effects |
|---|---|---|---|
| none -> active | `POST /api/assets/{slug}` with `paid_from` | exit (if `from_exit_id`) then cash locked and must belong to user (`fundings.py:116-133`); amount must be known (`:135-136`) and <= balance (`:137-138`); amount 0 -> no funding (`:139-140`) | cash debited, `balance_date = max(...)`, `prev_balance_date` stored (`:144-161`); funding is added after `db.flush()` so the holding id exists (`routers/assets.py:184-187`) |
| active -> active (amount changed) | `PUT` of fd/stock/bond/mf/gold/other cost | `plan_edit` (`fundings.py:215-266`): no funding -> no move; new cost <= 0 -> 422; out of sync -> save without moving money, note; account purged -> save, note; account soft-deleted -> 422; increase > balance -> 422 | `apply_edit`: cash -= delta; `funding.amount = new` (`:269-275`). Types rd, nps, cash, pf never adjust (`:166`) |
| active -> refunded | holding soft-delete | `refund` (`fundings.py:308-315`); fundings locked FOR UPDATE; row locked in router so a double delete refunds once | cash += amount (even when the account is soft-deleted); account purged -> only `refunded_at` set |
| refunded -> active | holding restore | `restore` (`fundings.py:318-338`): balance >= amount else 409 (different text when account deleted); account purged -> no debit | cash -= amount; `refunded_at = NULL` |
| any -> link NULL | purge of the cash account | purge SET NULLs funding rows (locked first, `purge.py:91-112`) | no balance change anywhere |
| any -> deleted rows | purge of the funded holding | `purge.py:170-174` | rows removed (refunded already) |
| `from_exit_id` -> NULL | purge of the exit's holding | FK SET NULL | exit no longer counts as reinvested |

### 2c. Illegal combinations

| Illegal | Prevented by |
|---|---|
| Two active fundings for one holding | UQ `uq_holding_fundings_active`; INV `duplicate_active_funding`, `missing_funding_unique_index` |
| Funding amount <= 0 | CHECK `ck_holding_fundings_amount_positive` |
| Active funding on a soft-deleted holding, or refunded funding on a live holding | INV `funding_state_mismatch`; MACHINE |
| Funding whose holding row is gone | INV `orphan_funding` |
| Negative cash balance | CHECK `ck_cash_holdings_balance_nonnegative`; INV `negative_cash`; API balance checks |
| Debit beyond balance on apply/restore/edit | API (`fundings.py:137,327,261`); MACHINE; TEST `tests/test_paid_from.py`, `tests/test_paid_from_edit.py` |
| Refund to a purged account moves money | API (`fundings.py:313`); TEST `test_known_bugs.py:117` |
| Edit that debits a soft-deleted account | API 422 (`fundings.py:257-258`); MACHINE edit_funded |
| Refund/restore of a soft-deleted account balance | API, `test_known_bugs.py:62,74,87` |
| Cash balance == initial + exits - active fundings ledger | MACHINE only (ideal-ledger check); no INV |
| Funding amount vs holding cost drift | allowed by design (SIP posting, CAS, RD growth); surfaced as `out_of_sync`; no INV |

### 2d. Duplicated guards

| Rule | Places |
|---|---|
| "Which cost a type has" (amount per type) | `fundings.amount_for` (`:83-100`), `stored_cost` (`:179-181`, uses `date.today()` not IST), web `lib/paid-from.ts`, MACHINE `cost_now` |
| "Which types adjust" | `EDIT_ADJUSTS` (`fundings.py:166`), `_edit_reason` (`:396-402`), web `lib/paid-from.ts`, MACHINE `ADJ_SLUGS`/`RUNNING_SLUGS` |
| "Soft-deleted account is still debited/credited" | `fundings._cash_of` (`:278-288`), `exits.undo_exit` (`exits.py:764-769`), `fundings._name_of` (`:205-212`); new-money paths (`_resolve_cash` `exits.py:511-520`, `fundings.plan` `:127-129`) use the default filter and refuse deleted accounts |
| Lock order | `fundings.plan` comment (`:117-118`), `routers/exits.py:242` comment, `purge.py:45-56`; tests `tests/test_locks.py`, `tests/pg/test_concurrency_pg.py`, `tests/pg/test_purge_hardening_pg.py` |
| Wording | `schemas/fundings.py` vs web `lib/paid-from.ts` (contract tests `tests/contract/`) |

### 2e. Gaps

- `stored_cost` uses `date.today()` (server local date), while creation uses `today_ist()` (`routers/assets.py:157`). For rd (not adjustable) it does not matter; for others the cost has no date dependence. Unverified for any date-dependent type; the RD exclusion (`fundings.py:166`) is what makes it safe.
- No INV for the cash ledger identity or for "funding in sync"; only MACHINE guards money conservation, and only in test data.
- `funding.funded_on` / `prev_balance_date` are recorded but never restored on refund (balance date left alone); no check anywhere (cosmetic, unverified whether SPEC wants it).
- Edit adjustments are exercised by MACHINE (`edit_funded`, `edit_running`); CAS and SIP posting out-of-sync paths are only covered by `tests/test_paid_from_edit.py` (unverified how many cases).

---

## 3. Exit (`holding_exits`)

### 3a. States

| State | Representation |
|---|---|
| Sale | `kind='sale'`; `quantity` set (null for Other); `prev_state.full` true/false/absent (legacy) |
| Settlement | `kind='maturity'`; `quantity NULL`; `destination` cash or none |
| Destination cash, account live | `destination='cash'`, `cash_holding_id` -> live cash, `cash_added` set |
| Destination cash, account soft-deleted | same, cash `deleted_at` set; undo still debits it |
| Destination cash, account purged | `cash_holding_id IS NULL` but `destination='cash'` and `cash_added` set (FK SET NULL, `holding_exit.py:54-56`); undo skips the debit |
| Destination none | `destination='none'`, `cash_holding_id NULL`, `cash_added NULL` (`exits.py:640-643,716-724`) |
| Latest vs older | derived: `max(id)` over (user, type, holding) (`exits.py:404-411`) |
| Reinvested | derived: sum of active fundings with this `from_exit_id` (`fundings.py:341-356`) |
| Created account | `prev_state.cash_created = true` when `cash_new` made the account (`exits.py:545-549`) |
| Removed (undone) | row deleted (`exits.py:835`) |

`destination` enum includes `renewed` and the table has `new_holding_id`, but no code in `app/` writes either (grep): unused columns.

### 3b. Transitions

| From -> To | Trigger | Guards | Side effects |
|---|---|---|---|
| none -> sale | sell | see lifecycle 1b | cash credited `cash_added`; `prev_state` has previous cash balance/date, quantity, invested, avg_nav, `full` |
| none -> maturity | settle | see 1b | same |
| sale/maturity -> removed | undo | latest only (`routers/exits.py:258-265`); not reinvested (`:267-274`); holding must be live (`:250-257`); cash must cover `cash_added` (`exits.py:771-784`) | see 1b; account created by the exit is kept (`exits.py:831-832`); balance clamped at 0 after the shortfall check (`:822`) |
| any -> cash link NULL | cash purge | FK SET NULL | none |
| any -> gone | holding purge | `purge.py:164-169` | none |
| reinvest (new funding with `from_exit_id`) | `POST /api/assets/{slug}` with `paid_from.from_exit_id` | exit locked FIRST and must belong to user (`fundings.py:116-126,132-133`) | exit becomes un-undoable until the new holdings are deleted |

### 3c. Illegal combinations

| Illegal | Prevented by |
|---|---|
| Undo of a non-latest exit | API 409 (`routers/exits.py:258`); MACHINE undo/undo_twice |
| Undo of an exit with active reinvestment | API 409 (`routers/exits.py:267`); lock order guarantees no race (`:266` comment); MACHINE reinvest; TEST `tests/pg/test_concurrency_pg.py` |
| Undo when the cash is short | API 409 (`exits.py:771-784`); MACHINE `spend_then_undo` |
| Double undo | exit row locked; second undo 404 (`routers/exits.py:243-244`); MACHINE undo_twice |
| Double sell/settle (double click) | holding row lock + `_not_active` / `already`; UQ for maturity; MACHINE sell_twice, settle_twice |
| Negative amount, cost, charges; quantity <= 0 | CHECK `ck_holding_exits_*` |
| Orphan exit | INV `orphan_exit` |
| `cash_added` != amount, `destination` vs `cash_holding_id` mismatch | none (set together in `exits.py:640-643`); no CHECK, no INV |
| `maturity` exit with a quantity or `sale` with NULL quantity (non-Other) | none beyond code paths |
| Exit date in the future / before purchase / before maturity | API (`exits.py:267-269,698-700`); no CHECK, no INV |

### 3d. Duplicated guards

- "Latest exit" is computed at `exits.py:404-411` (undo) and again, differently, as the last row in `fetch_exit_info` ordering by id (`exits.py:414-426`) for the grid; the web `lib/exits.ts` decides whether to show Undo.
- Reinvested amount: `reinvested_by_exit` is called in the undo router (`routers/exits.py:267`), the exits list (`:229`) and `fetch_exit_info`; the web shows "left in account" from `fundings.left_in_account` (`fundings.py:359-363`).
- Cash existence/ownership check: `_resolve_cash` (`exits.py:511-520`) and `fundings.plan` (`:127-133`) each re-derive it; both message `CASH_ACCOUNT_ERROR`.
- Date rules: sale rules in `check_sale`, settle rules in `record_settlement`, web `lib/exits.ts`.

### 3e. Gaps

- `cash_added`/`destination`/`cash_holding_id` consistency and "kind vs asset_type" combinations have no CHECK or INV.
- Exit dates are not validated against later SIP instalments or later exits (a second sale dated before the first): unverified; check `check_sale` for a lower bound from existing exits (none seen in `exits.py:253-290`).
- Unused columns `destination='renewed'`, `new_holding_id` are never written or read.

---

## 4. SIP (`mf_sips`, `mf_sip_skips`, instalment rows in `mf_transactions`)

### 4a. States

| State | Representation |
|---|---|
| Active | `status='active'` (`sip.py:35-37`); posts when `post_from <= today` |
| Paused | `status='paused'`; resume restarts from the next due date, missed months are lost (`routers/sips.py:282-285`) |
| Stopped ("Cancelled") | `status='stopped'`; terminal for edit/pause/resume; only delete remains |
| Past end date | derived: `end_date` reached; status stays `active`, `next_date_of` returns None (`sip.py:413-417`) |
| Linked to holding | `mutual_fund_id` -> live open fund |
| Unlinked | `mutual_fund_id IS NULL` (before first instalment, or the fund was purged: FK SET NULL, `mf_sip.py:38-40`) |
| Linked to sold fund | `mutual_fund_id` -> fund with `closed_on` set |
| Linked to soft-deleted fund | `mutual_fund_id` -> fund with `deleted_at` set (row hidden by the filter) |
| Skip | row in `mf_sip_skips` (UQ `(sip_id, due_date)`) |
| Instalment | `mf_transactions` row with `sip_id` set, UQ `(sip_id, txn_date)`; `sip.last_posted_on` = due date of the last one. A Buy more purchase is a different row: `sip_id` NULL, `manual` true (lifecycle 1) |

### 4b. Transitions

| From -> To | Trigger | Guards | Side effects |
|---|---|---|---|
| none -> active | `POST /api/sips` | scheme active (`routers/sips.py:119-129`); given holding must exist/live (404), same scheme (422), not sold (422) (`:132-150`); without a holding id, links the single open holding of same scheme+platform (`:151-161`); duplicate active SIP -> 409 unless `confirm_duplicate` (`:164-182`) | `post_from` = first due on/after start (or today); immediate `post_due` for that SIP (`:201`) |
| active -> paused | `POST /{id}/pause` | status must be active else 409 (`:262-263`) | none |
| paused -> active | `POST /{id}/resume` | status must be paused else 409 (`:278-279`) | `post_from` recomputed (`:282-285`) |
| active/paused -> stopped | `POST /{id}/stop` | not already stopped (`:300-301`) | none |
| any -> edited | `PUT /{id}` | stopped -> 409 (`:232-233`); end >= start (`:234-235`); day change recomputes `post_from` and prunes skips with a different day (`:237-246`) | none on instalments |
| (instalment) | `post_due` / `_post_one` | status active and `post_from <= today` (`sip.py:385`); re-read under lock: status still active and link unchanged (`:304-315`); dues from `due_dates` honouring skips, `last_posted_on`, `end_date` (`:317-323`); stops at the first missing NAV (`:331-333`) | see below |
| fund sold / deleted / purged | (no SIP write) | holding None or `closed_on` set -> re-point to the single open live holding of the same scheme+platform, else create a new holding at the first instalment (`:284-299,338-354`) | SIP keeps running; units never go into a sold or deleted fund |
| skip / unskip | `POST /{id}/skip`, `DELETE /{id}/skip/{date}` | skip needs active and an upcoming due date (`:323-338`); duplicate skip 409 (`:339-342`); unskip needs an upcoming date (`:371-372`) | skip row insert/delete |
| any -> deleted | `DELETE /{id}` | none | instalments' `sip_id` NULLed, skips deleted (`:388-393`) |

Instalment effects: `ensure_opening_transaction` (`sip.py:206-231`), MF units/invested/avg_nav raised (`:365-372`), a new holding is created when none (`:338-354`), `last_posted_on` advanced. History fetch happens before locks, never inside (`:255-271`).

### 4c. Illegal combinations

| Illegal | Prevented by |
|---|---|
| day_of_month outside 1-28, amount <= 0, end < start | CHECK `ck_mf_sips_*` |
| status outside active/paused/stopped | CHECK (`str_enum create_constraint`) |
| Duplicate instalment for a due date | UQ `(sip_id, txn_date)` + `last_posted_on`; MACHINE post_due |
| Duplicate skip | UQ `uq_mf_sip_skips_sip_due` |
| Instalment into a sold or deleted fund | API (`sip.py:294`, `_active_target` `:245`); INV none; MACHINE ("no purchase dated after `closed_on`", "posting never touches closed or deleted fund"); TEST `tests/test_sip_sold_fund.py` |
| SIP linked to a missing fund | FK SET NULL (Postgres); MACHINE `check` (`machine.py:1781-1786`); INV none |
| Posting while paused/stopped (race with pause) | re-check under lock (`sip.py:310`); TEST `tests/pg/test_concurrency_pg.py` (unverified which cases) |
| Two holdings created by concurrent posting runs | re-check `mutual_fund_id != linked_fund_id` (`sip.py:310`); TEST pg concurrency |
| Update of a stopped SIP | API 409 (`:232`); MACHINE sip_stop |
| Post to ended SIP | `due_dates` end_date filter; TEST `tests/test_sip.py`, `tests/test_props_sip.py` |
| `last_posted_on` beyond `end_date`/before `post_from` | none (no CHECK) |

### 4d. Duplicated guards

- "Sold fund takes no units": `routers/sips.py:148,156`, `services/sip.py:245,294`, CAS commit refusal for any exit (`routers/cas_import.py:127`), `services/duplicates.py:90`.
- Platform matching (lowercase, trim): `routers/sips.py:157`, `services/sip.py:246` (comment says create-time match); both inline.
- "Upcoming" test for skip: `routers/sips.py:330-336` and `:371` and web `lib/sip.ts`.
- Next-due maths: `sip.next_due`, `due_dates`, `routers/sips.py:238,282`, web.

### 4e. Gaps

- MACHINE rules: `sip_create`, `sip_create_twice`, `post_due`, `sip_toggle` (pause/resume), `sip_stop`, `double_create`; skip/unskip/update/delete only as cross-user 404 probes (`machine.py:1568-1574`). Unexercised: skip, unskip, PUT update (day change), delete SIP, SIP on a restored fund, two active SIPs to one fund.
- Pause/resume/stop/skip/update have no row lock (`routers/sips.py` has no `with_for_update`); safe because posting re-reads under lock, but unlocked concurrent update vs resume `post_from` write is unverified.
- Restoring a soft-deleted fund after the SIP already created a replacement holding yields two open holdings for one scheme+platform; `_active_target` then returns None (several matches) and creates yet another holding on the next linking attempt only if the SIP's link is missing. Unverified end state; check `tests/test_sip_sold_fund.py`.
- No INV query for SIPs at all.

---

## 5. Cash account

### 5a. States

| State | Representation |
|---|---|
| Live | `cash_holdings.deleted_at IS NULL` |
| Soft-deleted | `deleted_at` set (30-day window); still receives refunds and debits for holdings that point at it |
| Purged | row gone after 30 days; exits/fundings keep NULL `cash_holding_id` |
| Pointed at by | `holding_exits.cash_holding_id` (SET NULL), `holding_fundings.cash_holding_id` (SET NULL); `cash_new` exits create the row (`exits.py:543-549`); the cash row has its own funding like any holding (cash is a fundable type) |

### 5b. Transitions

| From -> To | Trigger | Guards | Side effects |
|---|---|---|---|
| none -> live | `POST /api/assets/cash`, or a sale/settle with `cash_new` | balance >= 0 CHECK; for `paid_from` same as funding apply | `Cash` row |
| live -> live | PUT (balance edit by user), exit credit, funding debit, refund, undo | CHECK balance >= 0; shortfall guards | balance changes; PUT of cash moves no funding money (`fundings.py:166`) |
| live -> deleted | `DELETE /api/assets/cash/{id}` | generic delete: cash has no exits so no 409 (`assets.py:294-311`) | its own funding refunded (`:315`); fundings of OTHER holdings that point at it stay active |
| deleted -> live | restore | generic restore; its own funding re-debited (409 if short) | |
| deleted -> purged | purge after 30 days | cash locked last (`purge.py:48,153-156`) | exits and fundings SET NULL; no balance move |
| deleted: as destination | sell/settle/reinvest | refused (default filter hides it; `exits.py:514-520`, `fundings.py:127-131`) | |
| deleted: undo/restore/refund | undo, restore, refund | still debited/credited (`include_deleted`) | restore 409 text asks to restore the account first |

### 5c. Illegal combinations

| Illegal | Prevented by |
|---|---|
| Negative balance | CHECK; INV `negative_cash`; API shortfall 409s |
| New money into a deleted or other user's account | API (default filter + `user_id`); MACHINE; TEST `test_known_bugs.py` |
| Lock-order deadlock between purge, restore and undo | lock order; TEST `tests/pg/test_purge_hardening_pg.py` |
| Cash balance != ledger | MACHINE only |
| Deleting an account that is the only source for active fundings | allowed; no guard, intended |

### 5d. Duplicated guards

Balance floor: CHECK, `exits.py:771-784`, `fundings.py:137,261,327`, `exits.py:822` clamp (`max(..., 0)`). Account lookup with user scope appears in `exits.py:511`, `fundings.py:127,205,278`, `exits.py:764`.

### 5e. Gaps

- INV checks only `balance < 0`; no check that a live holding's active funding points to an existing account row of the same user (cross-user link is unguarded by FK; API sets it from a user-scoped query only).
- `exits.py:822` silently clamps to 0 instead of failing: unreachable after the shortfall check unless concurrent change; locked by `FOR UPDATE`, so effectively dead.
- Soft-deleted cash with active exits/fundings: MACHINE `delete_linked_cash` and `purge_exit_cash` cover it.

---

## 6. Auth

### 6a. States

| State | Representation |
|---|---|
| User active | `users.is_active = true` |
| User deactivated | `is_active = false` (only the CLI `python -m app.jobs.users deactivate`, `app/jobs/users.py:53-61`) |
| Password-only / Google-linked / Google-only | `password_hash`, `google_sub` (unique) both nullable (`app/models/user.py`) |
| Refresh token live | row with `revoked_at NULL`, `replaced_at NULL`, `expires_at` > now |
| Refresh token rotated | `replaced_at` set; reuse within 60 s grace allowed |
| Refresh token revoked / family dead | `revoked_at` set on every row of `family_id` |
| Rate-limited | derived: >= 5 `login_attempts` with `succeeded=false` for the email in 15 min (`services/auth.py:21-25,210-221`) |
| Access token | stateless JWT, 15 min, `typ=access`; user re-read each request (`app/deps.py:9-25`) |

### 6b. Transitions

| From -> To | Trigger | Guards | Side effects |
|---|---|---|---|
| none -> user | `POST /api/auth/signup` | email in `ALLOWED_EMAILS`, not existing (`routers/auth.py:165-179`) | token pair |
| none -> user | Google first sign-in | verified email, allowlisted (`google_auth.py:99-115`) | `google_sub` set |
| password user -> Google-linked | Google sign-in with matching verified email | `google_sub` already set to another id -> error (`:108-110`) | automatic link, no confirmation |
| login | `POST /login` | rate limit 429 first (`:185-186`); inactive user counts as failed (`:192-193`) | attempt row; password rehash; `last_login_at`; new family |
| live -> rotated + new | `POST /refresh` | unknown/revoked/expired -> 401; inactive -> 401 (`services/auth.py:183-187`); rotated token after 60 s -> whole family revoked (`:188-192`) | rotated token marked; new row same family (`:194-195`); a rotated token inside grace issues another pair (`:193`) |
| family -> revoked | `POST /logout`, theft detection | unknown token returns False, no error (`:198-204`) | all rows in family revoked |
| active -> deactivated | CLI only | none | tokens are NOT revoked; effect via `rotate_refresh` and `current_user` checks |
| deactivated -> active | no code path (manual DB edit) | | |

### 6c. Illegal combinations

| Illegal | Prevented by |
|---|---|
| Duplicate email / google_sub | UQ on both; signup 409 / Google `IntegrityError` -> 401 (`routers/auth.py:176-179,222-224`) |
| Inactive user holds a working session | `current_user` DB check (`deps.py:23`), `rotate_refresh` (`auth.py:186`); TEST `tests/test_auth_api.py:99`, `tests/test_google_auth.py:155` |
| Reused rotated token after grace | `rotate_refresh`; TEST `tests/test_auth_service.py:100` |
| Brute force | rate limit; TEST `test_auth_api.py:109`, `test_auth_service.py:122` |
| Cross-user data access | every query filters `user_id`; TEST `tests/test_scoping.py`; MACHINE `cross_user` |
| Google-only user logging in by password | `verify_password(None, ...)` returns False (`auth.py:87-92`) |

### 6d. Duplicated guards

Active check: `deps.py:23`, `auth.py:186` (rotate), `routers/auth.py:192` (login), `google_auth.py:116`. Allowlist check: signup (`routers/auth.py:165`) and Google creation (`google_auth.py:111`); sign-in of an existing user does not re-check the allowlist.

### 6e. Gaps

- Deactivate leaves refresh tokens unrevoked and `set-password` appears not to revoke families (no `revoke` seen in `app/jobs/users.py` by grep; unverified, read `set_password`).
- `login_attempts` rows never pruned; no cleanup job seen (grep) (unverified). Success does not reset the failure window.
- Rate limit is per email string only, not per IP; unknown emails are recorded too.
- Within grace a rotated token can mint several live pairs in one family.
- No lifecycle test covers deactivate-then-refresh on Postgres; MACHINE has no auth rules (all calls use one harness user plus a second).

---

## 7. Import and sync markers

| Marker | Table / field | Meaning | Written by | Cleared / reset by |
|---|---|---|---|---|
| NPS history sync | `nps_nav_history_sync(scheme_id, synced_at)` (`models/nps_master.py:61-69`) | One-time history backfill done for this scheme; not "up to date" | `store_history` upsert (`services/nps.py:307-334`) via `sync_scheme_history` (skip if row exists, `:355-362`), background task after create/edit/restore (`routers/assets.py:190,271,345`), `sync_missing_history` in the nightly import (`:337-352`) | never; FK CASCADE with master. Daily append of the latest NAV is separate (`_append_today`, held schemes only, `:213-`) |
| Stock history backfill | `stock_price_history_sync(master_id, backfilled_at)` (`models/stock_price_history.py`) | 12 month-end backfill ran for this stock master | `backfill_month_ends` (`services/stock_history.py:120-161`): marker inserted for ALL `needed` stocks if at least one month was fetched | never; held-stock set read via ORM so deleted holdings are excluded (`:79-85`, relies on the soft-delete filter on a subquery; unverified) |
| MF NAV history | `mf_nav_history_sync(scheme_code, first_date, last_date, fetched_at)` (`models/mf_master.py:57-69`) | Last full mfapi fetch; bounds of stored history | `nav_history.store_history` (`:158-194`); `last_date` bumped by the daily append (`:291-300`); read by `resolve_nav` (`:229-257`) | overwritten on each refetch |
| MF refetch limit | `fetched_at` vs `REFRESH_AFTER = 24 h` (`nav_history.py:25,251`) | Within 24 h a missing historical NAV is answered `None` without a fetch | `resolve_nav` | after 24 h the next request may refetch. A failed fetch writes no marker (`NavSourceError`), so failures are not rate-limited (unverified) |
| Benchmark refresh | same `mf_nav_history_sync` row for scheme 120716 (`BENCHMARK_SCHEME_CODE`, `nav_history.py:262`) | Same as above for the Nifty 50 index fund | `refresh_benchmark_history` (`services/analytics_benchmark.py:44-58`) in the nightly AMFI import; skip if synced < 24 h ago | overwritten |
| SIP posting marker | `mf_sips.last_posted_on` | Due date of last posted instalment | `sip._post_one` (`:373`) | day change recomputes `post_from` only |
| Gold/silver rate backfill | none (no marker table) | Idempotence by data: `insert_missing` with `ON CONFLICT DO NOTHING`; PDF pass skips weekdays that already have a full gold row (`services/gold_history.py:311-343,354-`) | `python -m app.jobs.gold_backfill`, manual workflow | n/a |
| Purge clock | `deleted_at` itself | 30-day retention timer | soft delete | restore |
| Invariant check | none | stateless nightly read (`scripts/check_invariants.py`) | workflow `nightly-invariants.yml` | n/a |

Transitions: "unsynced -> synced" happens once per key and is never reverted. `held` filters differ: NPS and stock use ORM selects (soft-delete filter applies), MF uses raw SQL with an explicit `deleted_at IS NULL` (`nav_history.py:209-214`).

Illegal / risky combinations:

| Combination | Prevented by |
|---|---|
| Sync row without history rows (empty fetch) | none; NPS and MF record the marker even when the kept row list is empty (`nps.py:312-334`, `nav_history.py:179-183`); the empty NPS case is unverified (check whether `fetch_history` raises on empty) |
| Stock backfill marker set though some months or some stocks missed | none; marker is written when `months_fetched > 0`, for the whole `needed` set (`stock_history.py:152-158`); `months_missed` is only reported |
| Restored holding with a stale/never synced marker | NPS: re-scheduled on restore (`assets.py:345`); stock: next import backfills the unsynced master; MF: `resolve_nav` refetches on demand |
| History marker with `first_date` after the needed date | `resolve_nav` falls to refetch only after 24 h (`nav_history.py:241,251`) |

Gaps: none of these markers has an INV query or a MACHINE rule (MACHINE seeds markets directly, `world.py`). Covered by unit tests: `tests/test_nav_history.py`, `tests/test_nps_import.py`, `tests/test_stock_history.py`, `tests/test_analytics_benchmark_refresh.py`, `tests/test_gold_history.py`, `tests/pg/test_upserts_pg.py`.

---

## Summary of gaps (ranked by risk, money first)

1. **Deleted-with-exit and closed-with-maturity are guarded only by API.** `invariants.sql` has no query for a soft-deleted holding with an exit, a holding with both `closed_on` and a `maturity` exit, or a second sale after the full sale (`routers/assets.py:303-311`, `exits.py:675,560`). A bypass (script, restore of old data) would leave money in the books with nothing behind it.
2. **No INV or CHECK for the cash ledger identity** (initial + exits - active fundings). Only MACHINE guards it. Production drift (legacy refunded-to-deleted-account bug, `scripts/preflight_delete_refund.sql`) is invisible to the nightly check.
3. **Exit row internal consistency is unguarded:** `destination`/`cash_holding_id`/`cash_added` agreement, `kind` vs `asset_type`, quantity null rules, and unused `renewed`/`new_holding_id`.
4. **Undo with a purged cash account silently skips the debit** (`exits.py:764-784`): the sale proceeds remain in no account. Confirm SPEC §8b accepts this.
5. **MACHINE does not exercise:** CAS import (the other writer of units/invested), SIP skip/unskip/update/delete, SIP across fund restore, sold-in-part field edits, partly sold bond then maturity, all auth, all sync markers. Guards for CAS rely on `tests/test_cas_import_guards.py` only.
6. **SIP has no INV and its control endpoints take no row lock** (`routers/sips.py`); safety rests on the re-check in `_post_one` (`sip.py:304-315`). Restore of a deleted fund after a replacement holding exists is an unverified end state.
7. **Date-source split:** `fundings.stored_cost` uses `date.today()` while creation uses `today_ist()`. Safe only because RD (the date-dependent type) never adjusts.
8. **Auth:** deactivate/set-password do not revoke refresh families; `login_attempts` not pruned; Google auto-link without confirmation; grace window permits multiple live pairs.
9. **Sync markers are write-once and can be set on partial work** (stock backfill with missed months; NPS/MF with empty fetch). Failed MF history fetches are not rate-limited (unverified).
10. **Legacy dead paths:** `prev_state.stopped_sips` read in undo (`exits.py:807-816`) but never written.

---

## Where each guard lives

| Guard | Location |
|---|---|
| Soft-delete query filter | `app/models/base.py` (event), raw SQL repeats in `services/nav_history.py` |
| No edit when closed/settled; sold-in-part fields | `routers/assets.py:227-249`; list `schemas/assets.py:641-647`; web `lib/edit-guards.ts`; `tests/test_edit_guards.py` |
| No delete with exits | `routers/assets.py:294-311`; web `lib/delete-guard.ts`; `tests/stateful/test_known_bugs.py:130-175` |
| Refund on delete / re-debit on restore | `services/fundings.py:308-338`; router `assets.py:315,336` |
| Double delete / restore only once | row lock + recheck `assets.py:286-292,326-334`; `tests/pg/test_concurrency_pg.py`, `tests/test_locks.py` |
| Sale rules | `services/exits.py:253-290,325-340,556-663`; `routers/exits.py:123-166` |
| Settle rules, one settlement | `exits.py:666-731`; `routers/exits.py:169-214`; UQ `uq_holding_exits_maturity` |
| Undo rules (latest, reinvested, cash short) | `routers/exits.py:233-294`; `exits.py:754-836` |
| Reinvest vs undo lock order | `fundings.py:116-126`; `routers/exits.py:242,266` |
| Paid From plan/apply | `fundings.py:107-161`; `routers/assets.py:159-187` |
| Cost edit adjusts funding | `fundings.py:215-275`; `routers/assets.py:251-268` |
| One active funding per holding | UQ `uq_holding_fundings_active`; INV `duplicate_active_funding` |
| Funding active iff holding live | INV `funding_state_mismatch`; MACHINE |
| Cash >= 0 | CHECK `ck_cash_holdings_balance_nonnegative`; INV `negative_cash` |
| Orphan exits/fundings/MF txns | INV `orphan_exit`, `orphan_funding`, `mf_transaction_missing_fund` |
| `closed_on` needs a sale; sale cost | INV `closed_without_sale`, `sale_cost_vs_invested` |
| MF units equal transactions | INV `mf_units_vs_transactions` |
| Constraints validated | INV `invalid_constraint`; `tests/test_migration_0032.py` |
| CAS update refused when exits exist | `routers/cas_import.py:97-99,126-138`; `services/cas_import.py:246-263`; `tests/test_cas_import_guards.py` |
| SIP status transitions | `routers/sips.py:224-348`; `tests/test_sip_api.py` |
| SIP posting rules (sold/deleted/purged fund, lock re-check) | `services/sip.py:234-376`; `tests/test_sip_sold_fund.py`, `tests/test_props_sip.py` |
| Purge retention, lock order, timeout | `services/purge.py`; `routers/cron.py:99-104`; `tests/pg/test_purge_hardening_pg.py` |
| Session/token rules | `services/auth.py:149-204`; `deps.py`; `tests/test_auth_service.py`, `tests/test_auth_api.py` |
| Login rate limit | `services/auth.py:210-228`; `routers/auth.py:185-193` |
| Google link/create | `services/google_auth.py:99-124`; `tests/test_google_auth.py` |
| History markers | `services/nps.py:307-362`, `services/stock_history.py:120-171`, `services/nav_history.py:158-257`, `services/analytics_benchmark.py:44-58` |
| Whole-system money conservation | `tests/stateful/machine.py` (+ `reads.py`, `pg/test_money_machine_pg.py`) |

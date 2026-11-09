# HANDOFF — session resume notes (2026-11-08)

## Resume here — 2026-11-09 late night (wind-up: Wave B pushed and green; state-machine inventory and new invariants committed or pending locally, NOT pushed)

Wind-up requested by the user (/windup). Usage at wind-up: about 65% of the 5-hour window (resets about 15:50 UTC 2026-11-09 window; check `get_usage`). No subagents running. This section sits above the "2026-11-09 night" Wave B section, which is still accurate for T5, T8, T9, T10.

### Git state
- Pushed to origin/main: up to `4ab6f73` (Wave B; its deploy and web CI were green).
- Committed, NOT pushed: `d852c64` Docs: inventory of the implicit state machines (docs/STATE-MACHINES.md, ~450 lines).
- UNCOMMITTED, reviewed (I read the SQL line by line; the builder's pg invariant tests passed: 4 passed): `api/scripts/invariants.sql`, `api/tests/pg/test_invariants_script_pg.py`, `docs/SPEC.md` (§2 "Nightly invariant check"), `AGENTS.md` (one line). They add five nightly invariants: `deleted_holding_with_exit`, `closed_and_settled` (bond only), `exit_after_full_sale`, `exit_cash_mismatch`, `exit_kind_type_mismatch` (a second-maturity check was dropped, `duplicate_settlement` covers it). NOT yet confirmed: the full suites (`-m "not pg"` and `-m pg` with REQUIRE_PG=1) were started in the background at wind-up and not read. If the orchestrator's background runs are gone, re-run them. Draft commit message: write a new one (subject: "Tests: nightly invariants for exits (deleted with exit, closed and settled, after full sale, cash and kind mismatches)", end with the Co-Authored-By line). Commit as ONE command from the repo root: `git add AGENTS.md api/scripts/invariants.sql api/tests/pg/test_invariants_script_pg.py docs/SPEC.md && git commit -F <msgfile>`.
- The user said "commit and push all" just before the wind-up; the wind-up rule is never to push, so the push still awaits a fresh explicit OK (the earlier OK was given before the suites finished). After pushing check `gh run list --branch main --limit 3` once.
- Known limit of `exit_after_full_sale`: exit rows from before the `full` key in prev_state count as a full sale when closed_on equals the sale date; a same-day part sale plus the closing sale could false-alarm on very old rows (dev data shows 0).

### Dev data cleanup (DONE, committed in the database, user-approved)
The first run of the new invariant found 15 legacy exits on soft-deleted holdings (made 7 and 8 Nov, before the delete guard; all probe user 7). The user confirmed all dev data is test data and approved a hard delete. A script (scratchpad `cleanup_legacy_exits.py`, same order as purge.py, exact ids, one transaction) deleted 15 exits, 4 fds, 6 stocks, 2 mfs (+4 mf_transactions), 1 bond, 2 gold holdings. Cash accounts 5, 6, 7, 15 were not changed; one funding keeps a NULL from_exit_id. `deleted_holding_with_exit` = 0 afterwards, so tonight's nightly run should be green (the owner said the nightly runs at 21:00 UTC). Owner tasks done by the user: prod preflight run, GitHub `production` environment limited to `main`.

### Decisions made with the user this session (do not re-ask)
- Cost edit of a Paid-From holding adjusts the cash account (built, pushed).
- Sale cost after an edit: OPTION 2, TO BUILD: a partial sale of a mutual fund uses FIFO from the transactions only while the invested amount equals the sum of purchase transactions; otherwise proportional to the (edited) invested amount. Full sales already use the invested amount. This changes `sale_cost` in `api/app/services/exits.py` (money maths): needs a numbered plan, advisor plan review, tests (valuation/exits unit and property tests, the machine's sale-cost check that now skips edited funds must be restored), advisor diff review. The earlier "1902.95 vs 1880.09" machine oddity was most likely SIP postings after the edit, not a bug.
- Duplicate warning vs account balance order: NO CHANGE (balance check first).
- Net worth drift (stock with latest price but no history close): LEAVE (self-heals nightly; pinned as a strict xfail; the gold drift was already fixed, STATUS/HANDOFF notes that said two drifts are stale).
- Analytics: the user discarded the Tax-tab rename; "go back to the analytics items" is NEXT (list in docs/STATUS.md "Open (analytics)").

### State-machine inventory (docs/STATE-MACHINES.md) key gaps (medium priority, not decided)
Invariants for deleted-with-exit and exit consistency are now added (above). Remaining: the cash ledger identity cannot be checked from the DB (the starting balance is not stored; only the money machine checks it); undo with a purged cash account skips the debit (confirm SPEC §8b); SIP control endpoints take no row lock (re-check in `_post_one` protects); `fundings.stored_cost` uses `date.today()` while creation uses `today_ist()` (harmless: RD never adjusts); `prev_state.stopped_sips` is read but never written; machine does not cover CAS import, SIP skip/update/delete, auth, sync markers; deactivate/set-password do not revoke refresh families (a deactivated user is still rejected on access and refresh).

### Ordered next steps
1. Start the pg cluster if needed (`cd api && scripts/pg_test_cluster.sh start`; it may still be running: `scripts/pg_test_cluster.sh url`). Run `cd api && HYPOTHESIS_PROFILE=ci .venv/bin/python -m pytest -q -m "not pg"` and `TEST_DATABASE_URL=$(scripts/pg_test_cluster.sh url) REQUIRE_PG=1 HYPOTHESIS_PROFILE=ci .venv/bin/python -m pytest -q -m pg`; if green, commit the invariants (above), stop the cluster, ask the user for the push OK, push, check CI once.
2. Analytics items with the user, one by one (list in docs/STATUS.md; start with the tax-season ones: 2.16 harvesting, 2.15 unrealised gains, 2.21 tax-saving tracker, capital-gains gaps).
3. Offer the sale-cost option 2 build and the remaining state-machine follow-ups.

### Rules that bite
- Orchestrator + advisor + builders (Sonnet, effort medium, max 3 parallel); advisor (Opus, high) only for plan reviews and high-risk diffs; when the advisor says NOT OK, revise and send the plan back to the advisor BEFORE showing the user (the user called this out). Commits only as `git add <paths> && git commit -F <file>` in ONE command from the repo root (a trailing `&& git log` is blocked; run `cd` alone first if the shell is elsewhere). Never push without the user's OK.
- pg cluster port 5544 is orchestrator-owned (builders never start or stop it). Never touch ports 3000/8000 (the user's dev servers; a second `next dev` in web/ is blocked by theirs: use the scratchpad web copy recipe in the Wave B section).
- Probe account probe-ui3@example.test: password in `~/.config/wealth-track/probe.env` and the orchestrator's private memory `probe-account`; never write it into committed files. The user confirmed probe accounts hold no real holdings and dev data is test-only (this relaxes AGENTS.md rule 5 for probe-account data; still delete only by exact id).
- The user wants the wind-up on request or at 96% of the 5-hour window (tell at 85%).

## Resume here — 2026-11-09 night (testing Phase 3 Wave A pushed; Wave B committed locally, NOT pushed)

### Git state
- Pushed to origin/main: up to `21041d2` (Wave A: T1-T4, T6, T7, delete guard). Its gated deploy was green.
- Committed, NOT pushed (`git log origin/main..HEAD`): `61050df` API: editing the cost of a Paid From holding adjusts the cash account (T5a); `d383e7d` Web: the Edit dialog shows what a cost edit does to the Paid From account (T5b); `caa2bef` Tests: the machine edits the cost of Paid From holdings (T5c); `3ba658f` Tests: the machine covers rd, nps and pf (T9); `d383a5c` Tests: the machine spends cash and then undoes the sale (T10); plus the docs commit that adds this section. Pushing to main triggers the gated deploy (tests -> migrate -> deploy; the migrate is a no-op, there is no new migration); ASK the user first.
- Full suites at the last commit: `HYPOTHESIS_PROFILE=ci -m "not pg"` 2493 passed + 1 xfailed; `-m pg` (REQUIRE_PG=1) 204 passed; web vitest 407 passed.

### What Wave B did
- T5 (user decision 2026-11-09): editing the cost of a Paid-From holding adjusts the cash account. Rules in SPEC §8c "Edit": only fd, stock, bond, mf, gold, other; cash, pf, nps, rd move no money; money moves only when the holding is "in sync" (amount for the stored values equals the funding amount), otherwise the edit saves and a note says the account was not changed; order of checks: cost unchanged, new cost <= 0 (422), in sync, then purged (saves) / deleted (422 "Restore ... first") / short (422 on the cost field). Lock order holding -> funding -> cash. The API's paid_from carries `adjustable` and `reason`; the Edit dialog shows a live effect line and a red shortfall line. Advisor reviewed the plan three times (v1 and v2 were NOT OK) and the T5a diff (approved). Browser-checked on the probe account (effect line, red line, 422 with the same wording, a saved increase).
- T8 calibration (re-injecting 4 past bugs into `git archive` copies; table in the scratchpad `calibration-results.md`): the machine caught the deleted-cash-account bug and (SQLite) the SIP bug under ci; it missed "undo when cash is short" (fixed by T10) and the purge-lock race (only the pg concurrency tests catch it; no machine rule can).
- T9: rd, nps, pf in the machine (add, Paid From, edit_running = no money moves, delete/restore/purge, RD settle/undo, NPS scheme master seeded in world.py, read oracle on all ten types).
- T10: rule `spend_then_undo` (plus chaining after one in four sales); both injected bugs (undo cash-short refusal removed; NPS amount +1) now fail under ci.

### Open decisions and findings
- Possible issue, not investigated: after the user edits a fund's invested amount, a full sale recorded a cost (1902.95) that differed from the edited invested amount (1880.09). The sale cost follows the transactions, not the user's edit (or later SIP postings). The machine's sale-cost check skips its purchase-sum expectation for funds whose cost was edited. Ask the user whether the sale cost should follow the edited amount.
- Thin coverage: paid NPS adds on the pg machine are rare at the 25x25 budget (raising it costs > 45 s).
- Duplicate vs funding order (UX call, from before): with Paid From, a repeated create without `confirm_duplicate` returns 422 "More than this account's balance" when the account can no longer afford it.
- Known net worth drifts stay pinned as strict xfails (`api/tests/test_networth_today_agreement.py`).
- The user asked about implicit state machines; I offered a read-only inventory `docs/STATE-MACHINES.md` (holding lifecycle, funding, exit, SIP, cash account, auth, import sync markers: states, transitions, where each guard lives, gaps vs invariants and the machine). Not answered yet; offer it again.
- Owner tasks: run `api/scripts/preflight_delete_refund.sql` on prod (SELECT-only); limit the GitHub `production` environment to `main`; watch the first nightly invariant run (21:00 UTC).
- Analytics: the user DISCARDED "rename Interest & TDS tab to Tax"; the remaining analytics list is in docs/STATUS.md "Open (analytics)".

### Next steps
1. Ask the user whether to push the local commits; after a push check `gh run list --branch main --limit 3` once.
2. Offer: the state-machine inventory; the sale-cost-after-edit question; analytics items (from STATUS).

### Working notes
- Rules: orchestrator + advisor + builders; builders Sonnet effort medium, max 3 parallel; advisor only for plan reviews and high-risk diffs; when the advisor says NOT OK, revise and send it back to the advisor BEFORE showing the user a plan (the user called this out). Commits only as `git add <paths> && git commit -F <file>`, as ONE command with no `&&` after it and from the repo root (`cd` alone first if the shell is elsewhere). Never push without the user's OK. The user wants the wind-up on request or at 96% of the 5-hour window (tell them at 85%).
- pg cluster (port 5544) is orchestrator-owned; it is still running at the time of writing: `cd api && scripts/pg_test_cluster.sh stop` when done (`start` again before pg tests).
- Probe account for browser checks: probe-ui3@example.test; the password is in `~/.config/wealth-track/probe.env` (outside the repo) and in the orchestrator's private memory `probe-account`; never write it into committed files. The user confirmed probe accounts hold no real holdings and may be used freely on local test servers.
- Browser check recipe when the user's dev server (3000/8000) runs: the orchestrator cannot write project files or start a second `next dev` inside `web/`. Have a builder copy `web/` (without node_modules and .next) to the scratchpad with a node_modules symlink, set `turbopack.root: "/"` in the copy's next.config.ts, run the API on 8010 (`cd api && .venv/bin/uvicorn app.main:app --port 8010`) and `API_URL=http://localhost:8010 npx next dev --port 3010` in the copy; webpack mode renders no CSS (no postcss config), use turbopack. Create probe rows with unique names through the app's own API and delete them by exact id afterwards; stop both servers.

## Resume here — 2026-11-09 later (testing Phase 3 Wave A: T1, T2, T3, T6, T7 and the Delete guard committed; T4 half built, UNCOMMITTED; 5 commits unpushed)

(Superseded for git state and Wave A status by the section above; the Wave A task details below are still accurate.)

This section replaces the "Resume here — 2026-11-09 (testing Phase 3 Wave A…)" section below it for T1-T3 status; read both. Plan file (scratchpad, may be gone): `/private/tmp/claude-501/-Users-psy--claude-spares-spare-7qVS1Z/b85cc2c3-b50e-4717-8edd-bc54059e3674/scratchpad/plan-testing-phase3.md` (v2, advisor-reviewed). The user approved Wave A only; Wave B only after Wave A is verified and pushed.

### Git state
- Pushed to origin/main: up to `34160d2`.
- Committed, NOT pushed (`git log origin/main..HEAD`): `8c651ef` Web: disable Delete for sold or settled holdings; `90e6fea` pairwise concurrency tests (T6) and nightly invariant check (T7); `7c96c9e` earlier handoff notes; `a1aad98` T1 frozen clock + T2 read-side oracle; `7357a8d` T3 second user, double-submit, delete-409 rule. Pushing to main triggers the gated deploy (tests -> migrate -> deploy); ASK the user first.
- Uncommitted: `api/tests/stateful/world.py` and `api/tests/stateful/machine.py` (T4, below). Nothing else.

### Wave A status
- T1 (frozen clock), T2 (read oracle), T3 (second user, double-submit, delete 409 iff the holding has an exit), T6 (30 pairwise concurrency pairs), T7 (nightly read-only invariants): DONE and committed. Hunts passed (SQLite seeds 1..10 for T2, 1..5 for T3; pg 2-3 seeds). Last full-suite numbers before T4 (builder-run, T3): `-m "not pg"` 2474 passed + 1 xfail; `-m pg` 192 passed. No new app bug found by T1-T3/T6/T7.
- T4 (purge and time in the machine): HALF BUILT, uncommitted, builder stopped by the wind-up. DONE: `world.py` (CRON_SECRET patched into settings, `Harness.fk`, `backdate_deleted(table, id, age_days)` sets deleted_at to now - age + 1 h so exactly 30 days is kept and 31 purged without patching app code, `purge(via_cron)` runs `purge_deleted` or GET /api/cron/purge; on SQLite it emulates the FK actions by hand: MF transactions cascade, SIP/exit/funding cash links set NULL); `machine.py` (del_day on HM and CashM, FundM.cash_id may be None, delete/restore skip the money move when the link is None, rule `purge_after` advancing 0/1/30/31/45 days, back-dating, checking returned counts against the model, applying model changes, 404s for purged items, SIP links, a second purge through the other entry point must be a no-op; rule `delete_linked_cash`; invariant: no orphan MF transactions). Verified: `tests/stateful` under ci 12 passed in 47 s (before delete_linked_cash was added); the machine alone after it 1 passed in 43 s (209 purge steps, 8 removed something, 3 removed a cash account, 2 nulled a funding link, 0 nulled an exit link). NOT verified/done: pg machine run, detection proof, hunts, full suites, doc lines, docstring updates (`test_money_machine.py`, `test_money_machine_pg.py` and the machine header still say "no purge"). Known gap: exit cash-link nulling is never exercised (0 times); consider biasing the machine toward selling into a cash account that is then deleted and purged.
- Decision to confirm with the user (or just note): on SQLite the FK actions are emulated by the harness, so only the pg machine proves real FK behaviour. Fine in my view; the pg run is the proof.

### Ordered next steps
1. Start the pg cluster (orchestrator only): `cd api && scripts/pg_test_cluster.sh start`.
2. Brief ONE builder (effort medium) to finish T4: review the uncommitted diff first; update the stale docstrings; run `TEST_DATABASE_URL=$(scripts/pg_test_cluster.sh url) HYPOTHESIS_PROFILE=ci .venv/bin/python -m pytest -q -m pg tests/pg/test_money_machine_pg.py` (make the pg machine include purge; the pg harness has real FKs); bias toward exits pointing at a deleted cash account; prove detection in a `git archive HEAD | tar -x` copy under the scratchpad (break the cash-link nulling, the fundings deletion or the retention cutoff, not the real files); hunts SQLite seeds 1..5 (`HYPOTHESIS_PROFILE=hunt STATEFUL_EXAMPLES=300 STATEFUL_NO_SHRINK=1`) and pg 2 seeds; add one line each to docs/SPEC.md and AGENTS.md. Acceptance also: `HYPOTHESIS_PROFILE=ci .venv/bin/python -m pytest -q -m "not pg"` (1 pre-existing xfail) and `TEST_DATABASE_URL=$(scripts/pg_test_cluster.sh url) REQUIRE_PG=1 HYPOTHESIS_PROFILE=ci .venv/bin/python -m pytest -q -m pg`.
3. Read the T4 diff (key risks: no app code touched, deterministic clock, no wall-clock reads, the model rules match SPEC §8b/§8c purge text). Run the full suites once yourself, commit T4 (`git add <paths> && git commit -F <file>`), stop the pg cluster, then ASK the user whether to push the unpushed commits.
4. After the push is green (check `gh run list --branch main --limit 3`), offer Wave B (T5 PUT edit rule with the open question "should editing the cost of a Paid-From holding adjust the cash account? today: no"; T8 calibration by re-injecting 4 past bugs in a `git archive` copy; T9 rd/nps/pf in the machine) and the owner tasks below.

### Open decisions and owner tasks
- Duplicate vs funding order: with Paid From, a repeated create without `confirm_duplicate` returns 422 "More than this account's balance" when the account can no longer afford it, because the funding check runs before the duplicate check. The machine encodes it; the user may prefer the duplicate warning first (UX call).
- Known net worth drifts (gold carry-forward beyond the router's 14-day window; stock latest price with no matching history close) stay pinned as strict xfails in `api/tests/test_networth_today_agreement.py`; fix or leave? The read oracle cannot see the stock drift because the history's last point is overwritten; an interior-point check was declined for now.
- Owner: run `api/scripts/preflight_delete_refund.sql` on prod (SELECT-only); limit the GitHub `production` environment to `main`; watch the first nightly invariant run (`.github/workflows/nightly-invariants.yml`, 21:00 UTC): the "closed without a sale" check was never run on real dev data and may false-alarm (fix the query, do not ignore it).
- Stale lines in docs/STATUS.md ("Open follow-ups: lock every type's ids first; lock_timeout in purge") are done; remove them when updating STATUS.

### Rules that bite
- Orchestrator + advisor + builders: main agent plans, reviews and commits only; builders (Sonnet, effort medium) edit, max 3 in parallel; advisor (Opus, high) only for plan reviews and high-risk diffs. The hook allows only `git add <paths> && git commit -F <file>`. Never push without the user's explicit OK. Run git from the repo root (`git diff -- AGENTS.md` from `web/` hits web/AGENTS.md).
- The pg cluster on port 5544 is shared and orchestrator-owned; `stop` deletes its data dir; builders never start or stop it. Never run tests against Neon; probe rows only by exact id; never touch ports 3000/8000.
- The user armed an automatic wind-up at 96% of the 5-hour usage window (tell them at 85%, once). Probe account for browser checks: probe-ui3 (creds in ~/.config/wealth-track/probe.env, never print); never ask the user to sign in.

### Usage at wind-up
5-hour window 97% (resets 11:40 UTC, 2026-11-09), weekly 87% (resets 2026-11-10 15:00 UTC).

## Earlier — 2026-11-09 (testing Phase 3 Wave A: T6, T7 and the Delete guard committed; T1 and T2 built but UNCOMMITTED; T3 and T4 not started; nothing pushed since 34160d2)

### Where things stand
- Pushed to origin/main on 2026-11-09: everything up to `34160d2` (Phase 2 tests, purge hardening, the two money-bug fixes, docs). The API deploy run for it passed (tests, migrate no-op, deploy).
- Committed locally, NOT pushed (`git log origin/main..HEAD`): `8c651ef` Web: disable Delete for a holding that has a sale or settlement (browser-checked on the probe account); `90e6fea` Tests: pairwise concurrency tests and a nightly read-only invariant check.
- Plan file (scratchpad, may be gone): `/private/tmp/claude-501/-Users-psy--claude-spares-spare-7qVS1Z/b85cc2c3-b50e-4717-8edd-bc54059e3674/scratchpad/plan-testing-phase3.md` (v2, advisor-reviewed). User approved Wave A only; Wave B "after A is verified and pushed".

### Wave A tasks (from the plan)
- T1 Clock freeze for the stateful machine: BUILT, UNCOMMITTED, builder green (tests/stateful 12 passed, pg machine 1 passed, `-m "not pg"` 2474 passed + 1 xfail). Not yet line-reviewed by the orchestrator. Files: `api/tests/stateful/world.py` (FROZEN_DATE_MODULES: one clock = harness.today across valuation, cas_import, nav_history, gold_history and the portfolio/networth/holdings/analytics* routers), `api/tests/stateful/machine.py`, `api/tests/stateful/test_money_machine.py` (docstring), NEW `api/tests/stateful/test_clock_freeze.py`.
- T2 Read-side oracle: BUILT PARTLY, UNCOMMITTED, wound up mid-hunt. Same files as T1 plus NEW `api/tests/stateful/reads.py`. Adds: market-data rules (`set_stock_price`, `set_mf_nav`, `set_metal_rate`), stocks linked to a master, silver, and the oracle (grid rows = portfolio = dashboard per type; ids and invested amounts vs the model; cash vs model; dashboard "unsettled" list vs model), run every 5th step (`STATEFUL_READ_EVERY`; every step took 85 s) and in teardown. Last fix: `nav_on` in world.py uses the last history day on or before the day (it crashed 9/10 hunt seeds). Verified: `HYPOTHESIS_PROFILE=ci pytest tests/stateful` 12 passed in 28 s; pg machine ci passed in 15 s but BEFORE the nav_on fix. NOT done: SQLite hunt seeds 1..10 re-run (first round failed 9/10 on the nav_on test bug only; seed 7 passed; no app bug found), pg machine re-run, pg hunt (3 seeds), full `-m "not pg"`, one-line notes in docs/SPEC.md and AGENTS.md. No new strict xfails; no app bugs found by T2 so far.
- T3 Second user + double-submit (machine.py; cross-user ids -> 404, repeated POST -> clean 409/404 with no second money move): NOT STARTED.
- T4 Purge + time in the machine (rule purge_after(days); model: >30-day-deleted holdings vanish with exits/fundings, cash links null, no money moves, restore of purged -> 404, SIPs keep running; also in test_money_machine_pg.py): NOT STARTED.
- T6 Pairwise concurrency: DONE, committed `90e6fea` (30 pairs; 5 runs, no flake; whole pg suite 192 passed). Risk: the snapshot keeps row ids; could flake if sequence allocation changes.
- T7 Nightly invariants: DONE, committed `90e6fea` (12 SELECT-only invariants, READ ONLY transaction, workflow `.github/workflows/nightly-invariants.yml` 21:00 UTC on DEV_DATABASE_URL). Risk: the "closed without a sale" check was never run against real dev data and may false-alarm; watch the first nightly run, adjust the query rather than ignoring it.
- Delete guard (user request mid-session): DONE, committed `8c651ef`. Delete is disabled with a tooltip (API wording) in the grid row menu and details page when `item.exit != null`; undo re-enables. Browser-checked on the probe account (probe-ui3, creds in ~/.config/wealth-track/probe.env; never print). My probe row "zz-probe-delguard-*" (id 4, Other) was soft-deleted and sits in Recently deleted; it purges itself after 30 days. User also wants a machine check later: API delete returns 409 exactly when the holding has an exit (add to T3/T4 work in machine.py).

### Decisions already made (do not re-ask)
- Cash delete/restore moves money to or from a soft-deleted account; delete of a sold holding is blocked (409). SPEC §8c "Old data" and `api/scripts/preflight_delete_refund.sql` (owner runs it on prod, SELECT-only) cover old rows.
- Never fix app code inside a test task: write a strict xfail and report.
- Do not ask the user to sign in; probe creds are in ~/.config/wealth-track/probe.env.

### Decisions open for the user
1. T2: is a read check every 5th step acceptable (every step would exceed the ~30 s machine budget)? Also, the stock-price drift (latest price with no matching history close) can't be seen through the endpoints because the net worth history's last point is overwritten by today's value; add an interior-point check?
2. Wave B go-ahead after Wave A is verified and pushed: T5 PUT edit rule (open question: should editing the cost of a Paid-From holding adjust the cash account? today no), T8 calibration (re-inject 4 past bugs in a `git archive` copy), T9 rd/nps/pf in the machine.
3. Fix the two known net worth drifts (gold carry-forward window of 14 days in the router; stock price without a history close)? Pinned as strict xfail in `api/tests/test_networth_today_agreement.py`.
4. The owner still has to run `api/scripts/preflight_delete_refund.sql` on prod, and set the GitHub `production` environment to deployments from `main` only.

### Ordered next steps
1. Start the pg cluster (orchestrator only; builders never stop it): `cd api && scripts/pg_test_cluster.sh start`.
2. Brief ONE builder (effort medium) to finish T2: re-run the SQLite hunt (`HYPOTHESIS_PROFILE=hunt`, seeds 1..10), pg machine ci, pg hunt 3 seeds, triage (test bug / new app bug as strict xfail in tests/stateful/test_known_bugs.py / documented difference), add the SPEC and AGENTS lines. Acceptance: `HYPOTHESIS_PROFILE=ci .venv/bin/python -m pytest -q tests/stateful`; `TEST_DATABASE_URL=$(scripts/pg_test_cluster.sh url) HYPOTHESIS_PROFILE=ci .venv/bin/python -m pytest -q -m pg tests/pg/test_money_machine_pg.py`; `HYPOTHESIS_PROFILE=ci .venv/bin/python -m pytest -q -m "not pg"` (expect 1 pre-existing xfail plus any reported).
3. Read the T1+T2 diff (`git diff -- api/tests/stateful`, reads.py, test_clock_freeze.py), key risks only: determinism (same result twice), no wall-clock reads, oracle compares across endpoints and does not re-derive values.
4. Then T3, then T4 (sequential, same files), each with the machine check "delete is 409 iff the holding has an exit".
5. Full suites once: `-m "not pg"` and `-m pg` with `REQUIRE_PG=1`; web `cd web && npx next typegen && npx tsc --noEmit && npm run lint && npm test` if web changed. Commit T1+T2 (one commit), T3, T4 with messages in the scratchpad (`git add <paths> && git commit -F <file>`), update STATUS/HANDOFF/AGENTS, stop the pg cluster, then ASK the user before pushing (push to main triggers the gated deploy: tests -> migrate -> deploy).
6. After the push is green, offer Wave B.

### Rules that bite
- Orchestrator + advisor + builders: main agent plans, reviews, commits; builders (Sonnet, effort medium) edit; advisor (Opus, high) only for plan reviews and high-risk diffs; max 3 builders in parallel (the user once allowed a 4th for a web change). Never push without the user's explicit OK.
- Hook: main agent cannot edit project files; commits only as `git add <paths> && git commit -F <file>`. Builders cannot run git stash/checkout/restore/reset.
- `git diff -- AGENTS.md` run from `web/` hits web/AGENTS.md; run git from the repo root.
- The pg cluster on port 5544 is shared; `stop` deletes its data dir. Never touch Neon from tests; modify only your own probe rows by exact id; never touch ports 3000/8000.
- The wind-up at 95% of the 5-hour usage window was requested by the user ("/windup auto" behaviour): tell them at >= 85%, wind up at >= 95%.

### Usage at wind-up
5-hour window 81% (resets 11:40 UTC, 2026-11-09), weekly 84% (resets 2026-11-10 15:00 UTC).

## Earlier — 2026-11-09 (testing Phase 2 done, money-bug fixes committed, pushed)

Status: testing Phase 2 and the money-bug fixes are committed on `main` (HEAD `a1be995`); unpushed: see `git log origin/main..HEAD`. Nothing running.

### What exists
- Hypothesis profiles (`api/tests/hypothesis_profiles.py`), property tests (`api/tests/test_props_*.py`), contract tests (`api/tests/contract/`; refresh the snapshot with `cd api && .venv/bin/python -m tests.contract.update_snapshot`), the stateful money machine (`api/tests/stateful/`, `api/tests/pg/test_money_machine_pg.py`), purge hardening (`api/app/services/purge.py`, 503 on lock timeout).
- Fixes: Paid From delete/restore against soft-deleted cash accounts; delete of a sold holding blocked (409). Details in STATUS.md and SPEC §4, §8b, §8c.

### How to run everything
- Non-pg: `cd api && .venv/bin/python -m pytest -q -m "not pg"` (CI-like: prefix `HYPOTHESIS_PROFILE=ci`).
- Postgres: `cd api && scripts/pg_test_cluster.sh start && TEST_DATABASE_URL=$(scripts/pg_test_cluster.sh url) .venv/bin/python -m pytest -q -m pg`, then `scripts/pg_test_cluster.sh stop`.
- Web: `cd web && npm run lint && npm test`.
- Hunt: `HYPOTHESIS_PROFILE=hunt`; also `STATEFUL_EXAMPLES`, `STATEFUL_PG_EXAMPLES`. A failure is a finding: reproduce it as a deterministic test, never fix app code in a test task.

### Push
Awaiting the user's OK. A push touching `api/` starts the gated prod migrate and deploy (tests first).

### Open
- Owner: run `api/scripts/preflight_delete_refund.sql` on prod (SELECT-only); limit the GitHub `production` environment to `main`.
- Net worth today-point drifts (strict xfails in `api/tests/test_networth_today_agreement.py`), `analytics_returns._q` half-even rounding, always-0 `sips_cancelled`.
- Phase 3 testing; audit backlog #25, #26, #16, #23, #17, #18.

### Next steps, in order
1. Owner runs the preflight on prod.
2. Decide the push.
3. Phase 3 testing or the audit backlog.

## Earlier — 2026-11-08 night (testing Phase 1 pushed, CI gate verified green)

Status: testing Phase 1 is pushed to `origin/main` (2f53abd..69d3de2). The first real CI run on GitHub is green: API deploy run `42505519437` and CI Web run `42505519175`. One local commit is unpushed: the `actions/setup-node` bump to `@v7` in `ci-web.yml`. Nothing running.

### Commits (pushed)
- `b56c4a1` real-Postgres harness (`pg` marker, throwaway database, migration tests)
- `27419e3` CI: `ci-api.yml`, `ci-web.yml`; `api-deploy.yml` `tests` job gates the migrate and deploy
- `5a963ef` real-Postgres behaviour tests (constraints, search, upserts, FOR UPDATE paths)
- `cd1e4b7` real concurrency scenarios (34 pass; the strict xfail was a real bug)
- `35656d0` purge locks the holdings it deletes and re-checks them (fixes the restore vs purge race)

### How to run the pg suite
- Default, no DB: `cd api && .venv/bin/python -m pytest -q -m "not pg"`
- Real Postgres: `cd api && scripts/pg_test_cluster.sh start && TEST_DATABASE_URL=$(scripts/pg_test_cluster.sh url) .venv/bin/python -m pytest -q -m pg`, then `scripts/pg_test_cluster.sh stop`. `REQUIRE_PG=1` makes a missing URL fail (exit 4).
- Never point `TEST_DATABASE_URL` at Neon. Tests that need Postgres go in `api/tests/pg/`.

### Verified (local only)
- `-m "not pg"`: 2,407 passed + 1 strict xfail (net worth drift c2).
- `-m pg`: 149 passed. The 34 concurrency tests looped 20x with no flake.
- GitHub Actions (2026-11-08, after the push of `main`): API deploy run `42505519437` ran the tests without Postgres, then with Postgres (service container `postgres:16`), then migrate (a no-op) and deploy. CI Web run `42505519175` passed (next typegen, tsc, lint, vitest on Node 24, 1m31s).
- GitHub warned that `actions/setup-node@v4` targets the deprecated Node 20 runtime. Bumped to `@v7` in `ci-web.yml` (v7.1.0), committed locally, NOT pushed yet.

### Gates, in order
1. Dry run on a non-main branch: not done. The user chose to push `main` directly.
2. Push `main`: done 2026-11-08 (2f53abd..69d3de2). Pushing the `setup-node` bump is a separate push and needs the user's OK. A push touching `api/` or `ci-api.yml` starts the prod migrate and deploy, which waits for the tests.
3. Open, user setting: limit the GitHub `production` environment to deployments from `main` (a setting, not code).

### Follow-ups (not done)
- Purge: lock every type's ids first, then delete (rare cross-type deadlock between FK SET NULL on funding rows and a restore of a pf/other holding).
- Purge: `SET LOCAL lock_timeout` so a stuck lock fails the cron cleanly.
- Product search has no typo tolerance (tests assert typos return nothing). Product decision, not a bug fix.
- Coupling: `tests/pg` imports constants from `test_db_constraints.py` and `test_nps_import.py`.

### Roadmap (not built)
- Phase 2: property-based and stateful money tests (hypothesis); OpenAPI snapshot and generalised message parity tests.
- Phase 3: web component tests (jsdom + Testing Library); Playwright smoke flows on a throwaway stack; nightly read-only invariant check; coverage and xdist.

### Next steps, in order
1. Ask the user for the production environment setting (gate 3), and the OK to push the `setup-node@v7` commit.
2. Phase 2 only when the user asks.

## Resume here — 2026-11-08 night (wind-up at 99% usage; gold-rule commit done, nothing running)

Status: everything is committed. 2 commits are ahead of origin/main and unpushed: `3013df2` (net worth gold rule) and `f279662` (wind-up handoff); this docs update will be a 3rd. Everything before them (up to a7d0c22) is pushed. No builders or advisors are running. The working tree is clean (verify with `git status --short`). Usage at wind-up: 5-hour window 99%, resets 2026-11-08 16:40 UTC; weekly 68%.

### Done this session (all pushed except the last item)
- Wave 1 and Wave 2 of the invariants audit (locks, edit guards incl. identity fields, CAS re-import guards), pushed.
- DB constraints: migration 0032 (37 CHECKs + the partial unique index uq_holding_fundings_active), applied on dev and prod (the user ran the preflight on prod: no violating rows), pushed.
- Batch 2: #11 (refuse a partial sale that leaves no cost), #9, #14 (returns XIRR counts sale proceeds and fully sold holdings), #27 (delete pending states), pushed.
- Batch 3, pushed: undo refused with 409 when cash is short (closes the Paid From refund money-creation hole), a full sale no longer stops SIPs, SIPs keep running when their holding is sold/deleted/purged (units go to the user's single active holding of the same scheme+platform, else a fresh holding; a sold or deleted holding is never changed; creating a SIP for a previously sold fund is allowed; explicit sold id on create -> 422 "This holding has been sold"), NAV history fetched before row locks, CAS commit locks in id order, cash balance may be 0, Settle IntegrityError mapping (#10), net worth today-point agreement tests (#15 test-only).
- UNPUSHED commit: "Net worth history carries the latest gold rate forward, as the dashboard does" (services/networth.py: after the last known rate for a metal+purity, carry it forward with no 7-day limit; the 7-day rule stays between two rates and before the first rate). API suite at that commit: 2,386 passed + 1 xfail (case c2 documented drift). Web 394 passed (unchanged). I read the 3-line diff; no advisor review (not high-risk). docs/SPEC.md net worth drift bullet updated; STATUS.md and HANDOFF.md do NOT yet mention this commit.

### Owed / open
1. PUSH the gold-rule commit only on the user's explicit OK (push triggers the API deploy workflow; no migration). I did not check the last two deploy runs' results (`gh run list --repo Psyphon361/wealth-track --limit 3`).
2. Router window for gold rates: api/app/routers/networth.py loads rates only from 14 days before the chart start; if the latest rate is older than that window nothing loads and the history uses cost. Widen the window (needs a small change + test) — decision/OK not yet asked.
3. Net worth drift case (c2) remains (strict xfail): a stock whose latest price has no matching close in stock_price_history; ₹500 difference in the test. Not decided.
4. Docs to refresh: STATUS.md and HANDOFF.md must record the gold-rule commit and that drift (b) is closed (SPEC already says so).
5. Remaining audit backlog (see STATUS.md): #25 restore skips the duplicate check; #26 chart.tsx toLocaleString without en-IN + schemas/sip.py messages with no web mirror; #16 duplicated totals maths (holdings.py:330-345); #23 unused 'renewed' enum; #17 login lockout per email only (no IP limit, none on signup/refresh/google); #18 login_attempts/refresh_tokens never purged; #19 CI runs no tests or lint (the user's parked full-test-suite work; would also give real Postgres race tests); PF opened_on <= balance_date has no API rule (needs the user's approval to add API + form rule); drop the always-0 `sips_cancelled` (API + web/lib/exits.ts:73) — optional.
6. Observations not investigated: details pages took 10-60 s to load on the dev server (Next dev compile + Neon latency); a sold bond's details page still shows current value/gain/"days left" as if held; the Undo confirm dialog text is static UI text.
7. Not browser-verified: SIP posting after a sale/delete (unit-tested only), the sell dialog's new SIP note, the Settle error toasts, the gold carry-forward on the chart.

### Decisions the user made (do not re-ask)
Block a short undo; allow cash 0; SIPs are independent of holding records (keep running after sale/delete; undo after a SIP moved is allowed -> two active holdings, no auto-merge); returns include fully sold holdings as realised; refuse (not clamp) a partial sale with no remaining cost; undo allowed-with-message was REPLACED by block; net worth: align the gold rule (done as carry-forward after the latest rate).

### Rules that bite
- Orchestrator hook: the main agent can only run `git add <paths> && git commit -F <file>` (no cd, no extra && steps; use absolute paths), message files in the scratchpad; builders do all edits. A trailing `&& git status` is blocked. Writes to ~/.claude memory via Edit/Write are fine; `>>` redirects are blocked.
- Never push without the user's explicit OK. Never ask the user to sign in to test accounts (memory: dont-ask-user-to-sign-in); the user typed the probe password in chat this session and the Browser pane is signed in as probe-ui3@example.test (do not repeat the password anywhere). Use the user's running web on localhost:3000 (a second `next dev` in the same folder cannot start); seed probe rows via a spare API on 8010 (stop it afterwards); probe rows must be prefixed (PROBE-W5 next), deleted by exact id, soft-delete only. All PROBE-W3/W4 rows are already soft-deleted.
- Use `with_for_update(of=Model)`; model CheckConstraints go in the `_checks` tuple (TimestampedMixin hook); constraints need a matching migration with identical names (tests/test_migration_0032.py pattern).
- Advisor only for high-risk diffs (money, locks, migrations, auth, deletes) and non-trivial plans; at most one review per task; effort "high"; builders/scouts effort "medium"; max 3 builders in parallel.
- Tests: `cd api && .venv/bin/python -m pytest -q`; `cd web && npx tsc --noEmit && npm run lint && npm test`.

### Next steps, in order
1. (done) Read this section, docs/STATUS.md, docs/SPEC.md §2/§5/§8a/§8b. Check `git status --short` (clean) and `git log origin/main..HEAD --oneline` (expect 1 commit).
2. Ask the user: push the gold-rule commit? Then (with OK) `git push origin main`.
3. (done) STATUS.md and HANDOFF.md updated for the gold-rule commit (drift (b) closed, 14-day window item); docs commit still to do.
4. Offer the user the next item (priority: gold router window + test; #25; #26; #16; #23; security #17/#18; PF opened_on rule; CI plan when they ask).

## Resume here — 2026-11-08 night (audit batch 3 committed, unpushed)

Committed on `main`, NOT pushed (4 commits ahead of origin): `1149f2d` (cash balance 0 allowed), `e325fa7` (SIPs keep running for sold, deleted or purged holdings; NAV fetched before row locks), `4fa8036` (short undo refused 409; full sale keeps SIPs; Settle errors accurate), `fd786ad` (net worth today-point tests).

- Suites: API 2,381 passed + 2 strict xfail, web 394 passed, tsc and lint clean.
- Browser-verified (probe account): short undo refused with the API toast, holding and sale unchanged; cash account at ₹0 saves in Edit; SIP form "Add to" hides the sold holding. Not verified: SIP posting after a sale or delete (unit tested), the sell dialog's new note, the Settle error toasts.
- Decisions (user, 2026-11-08): block a short undo; allow cash 0; a full sale does not stop SIPs (a SIP is independent of its holding record; it posts into the user's one active holding of the same scheme and platform, else a fresh holding); creating a SIP for a sold fund is allowed; explicit sold holding id on create is 422 "This holding has been sold"; undo after a SIP moved is allowed (two active holdings, no auto-merge); #15 test first, no behaviour change.
- Open: net worth drift (SPEC §5: gold rate older than 7 days; stock price with no matching history close) needs the user's decision; audit items 16, 17, 18, 19, 21, 23, 25, 26, PF `opened_on` <= `balance_date`; drop `sips_cancelled`; observations (slow details pages on dev, sold bond details page). Full list in STATUS "Audit batch 3".
- Next, in priority: (1) ask the user about the net worth gold-age rule (recommendation: same rule in history and dashboard, or flag a stale rate); (2) 25, 26, 16, 23; (3) security 17, 18; (4) parked CI tests and lint (19).
- Push gate: ask the user first (API commits trigger the prod deploy). Run `git log origin/main..HEAD --oneline` and count before reporting the number.
- User rule (saved in memory): never ask the user to sign in to test accounts; use the persistent probe account.

## Resume here — 2026-11-08 late (audit batch 2 committed)

Committed on `main`, NOT pushed (8 commits ahead of origin: `152a51b`, `8d1f618`, `62fe16d`, `b5c2f3f`, `ec4fb80`, `2eca602`, `40f7846`, `78896fb`): `2eca602` (#11 refuse a partial sale that leaves no cost; #9 undo reports what was really taken out), `40f7846` (#14 returns XIRR counts sale proceeds and fully sold holdings), `78896fb` (#27 delete pending states). Docs: SPEC §5, §8b, §9; STATUS.

- Suites: API 2,349 passed, web 393 passed, tsc and lint clean.
- Browser-verified (probe account): grid delete pending, details-page delete pending, undo message for a short balance, Returns tab numbers. Not verified: the #11 refusal toast, the dialog fade-out title fix.
- Gate: migration `0032` waits on the user running `api/scripts/preflight_0032.sql` on prod. Nothing pushed; push only on the user's explicit OK (API commits trigger the prod deploy).
- Open audit items: 10, 12, 13, 15, 16, 17, 18, 19, 21, 23, 25, 26, PF `opened_on` <= `balance_date`. Details and the new findings (a)-(d) are in STATUS ("Audit batch 2").
- Next: pick from the open audit items by priority, 10, 12, 13, 15 first.
- User rule (saved in memory): never ask the user to sign in to test accounts; use the persistent probe account.

## Resume here — 2026-11-08 night (DB constraints committed, gated)

Committed on `main`, NOT pushed, NOT applied to prod (applied to the Neon dev DB on 2026-11-08, see gate 1): `152a51b` (CHECKs declared on the models, SIP first-instalment fix, CAS zero amount/units rejection, no opening row when invested <= 0) and `8d1f618` (migration `0032`: 37 CHECKs + `uq_holding_fundings_active`). Full API suite 2,322 passed at the time (2,349 now). Docs: SPEC §2 "Database constraints", §8, §8a; STATUS; AGENTS.md.

Gates (both need the user):
1. DONE (2026-11-08): 0032 applied to the Neon dev DB after a preflight with 0 violating rows; 37 of 37 constraints and the unique partial index verified; `downgrade -1` and `upgrade head` round trip OK; row counts unchanged; dev left at 0032.
2. The user runs `api/scripts/preflight_0032.sql` (SELECT-only counts) on prod, all must be 0, then says push. Possible failure: `mf_transactions` with 0 amount or units from older CAS imports; have a targeted fix ready. The migration is atomic and the deploy workflow runs it before the Vercel hook, so a failure leaves the old code live.

Open questions for the user: PF `opened_on <= balance_date` (needs API/form change).

Next batch (scout facts; re-scout if needed):
- #14 Returns XIRR ignores partial-sale proceeds: `analytics_returns.py` `holding_flows` ignores `holding_exits`; fully sold holdings are dropped by `_active_holdings` (`services/analytics.py:282`), partly sold ones lose the sale proceeds as a positive flow.
- #11 `exits.py` `sale_cost` caps at invested (l.196) and `remaining_after` (l.199-207) can leave invested 0 with units left; MF `avg_nav` becomes 0.0000.
- #9 `undo_exit` (`exits.py:779`) clamps cash at 0 but l.786 reports the full `cash_added`; `routers/exits.py:242-256` builds the message from it.
- #27 Delete flows without a pending state: `portfolio.tsx` `handleDelete` (l.181-196, optimistic), `holding-detail.tsx` `handleDelete` (l.157-166), shared `components/portfolio/delete-dialog.tsx` (button l.57-66). Pattern to copy: `sip-actions.tsx` `ConfirmDialog` (l.107-150, "Deleting…").

## Resume here — 2026-11-08 night (Wave 1 and Wave 2 committed, docs done)

Committed on `main`: `567e2aa` (sold bond payouts), `bd27705` (cash grid refresh), `adfa3b2` (row locks), `a324634` (lock order fix, SIP re-check under lock), `9592502` (CAS re-import guards), `225c1f9` (edit guards). Docs (SPEC §4, §8, §8a, §8b, §8c, STATUS, AGENTS.md) are written. Full suites green: API 2,230 passed, web 393 passed, tsc and lint clean. The identity-field lock commit follows `0d30fca`. Advisor findings are fixed (reinvest vs undo lock order, stale SIP under lock, future statement date, vitest alias in `lib/edit-guards.ts`).

- Nothing pushed. Push only on the user's explicit OK; API commits trigger the prod deploy.
- Not yet browser-checked. Check with probe rows only (rule 5), spare ports 8010+/3010+: T5 add a holding with Paid From, then open the Cash grid; delete and restore it. T4 a sold bond's details page, Bond payouts card with no coupons left. Edit hidden on the Closed tab and on a sold holding's details page. Edit dialog of a partly sold holding shows quantity/units/invested/price/purchase date read-only with the helper text. CAS preview badge and disabled Update Existing for a fund with a sale. SIP rows kept after a re-import.
- DONE (2026-11-08): identity fields are locked after a partial sale (`SOLD_IN_PART_FIELDS` in API `schemas/assets.py` and `web/lib/edit-guards.ts`; uncommitted, its own commit). Stock: `master_id`, `symbol`, `exchange`, `quantity`, `avg_buy_price`, `buy_date`; bond: `master_id`, `isin`, `quantity`, `purchase_price`, `invested_amount`, `purchase_date`; MF: `scheme_code`, `units`, `avg_nav`, `invested_amount`, `purchase_date`; gold: `metal`, `purity`, `weight_grams`, `invested_amount`, `purchase_date`; other: `invested_amount`, `acquired_on`. Open question for the user: name is not locked (the API overwrites it from the master when `master_id`/`scheme_code` is set), so a manually entered holding (no master) can still change its name after a partial sale.

## (Superseded) 2026-11-08 later — notes from before the commits, kept for the sections it references

Superseded by the section above; only the "Next steps" are obsolete.

### (old heading) Wave 2 built, UNCOMMITTED

Supersedes section "0. Progress" below for what to do next. Wave 1 is committed (`567e2aa`, `bd27705`, `adfa3b2`). Everything in this section is in the working tree, uncommitted, because the user said "wind up" at the usage limit. Nothing was reverted. Push only on the user's explicit OK (still 4 unpushed commits).

### Advisor review of adfa3b2 (done)
No blocking issues. Two real gaps were found and fixed in the working tree (not yet committed):
- Reinvest vs undo deadlock: `services/fundings.py` `plan` now locks the exit row BEFORE the cash row (undo locks exit, holding, cash). Errors are raised after both locks, cash error first.
- Stale SIP in posting: `services/sip.py` `_post_one` re-reads the MfSip row under lock (`with_for_update(of=MfSip)`, `populate_existing`) after the fund lock and posts only if still ACTIVE.
- Plus: FD `FOR UPDATE OF fixed_deposits` SQL test, reinvest lock-order test and stale-SIP test in `api/tests/test_locks.py`, honest comments on the sequential double-request tests (they prove the re-check, not the lock), a comment at `routers/exits.py` undo.
- Files: `api/app/services/fundings.py`, `api/app/services/sip.py`, `api/app/routers/exits.py` (comment), `api/tests/test_locks.py`. Targeted run: 221 passed. I read this diff; no second advisor review was run (it came from the advisor's own advice).
- Commit message already drafted at `/private/tmp/claude-501/-Users-psy-dev-mvp-wealth-track/3e3e9708-9de4-442f-9e45-6894f8ad1d0b/scratchpad/commit-lockfix.txt` (scratchpad may be gone; rewrite it if so). Commit as `git add api/app/services/fundings.py api/app/services/sip.py api/app/routers/exits.py api/tests/test_locks.py && git commit -F <file>`.

### T3 CAS re-import (behaviour B) — built, advisor-reviewed, blocking fix applied; needs the full suites then commit
Files: `api/app/services/cas_import.py`, `api/app/routers/cas_import.py`, `api/app/schemas/cas_import.py`, `api/tests/test_cas_import_guards.py` (new), `web/components/forms/cas-import/preview-step.tsx`, `web/lib/types.ts` (CAS types), `web/lib/cas-import.ts` + `cas-import.test.ts` (new).
- Preview returns `has_sales` on each existing match and on the row (any holding_exits row for that mf holding). Web: badge "Has sales recorded here", Update Existing disabled for a single-match row with sales, action forced to Add as New, row unticked by default, one-line helper.
- Commit: update of a fund with a sale → 422 "Couldn't import — nothing was saved" / "<fund> — Sales are recorded for this fund here, so use Add as new or skip it", all-or-nothing, checked again after `with_for_update(of=MutualFund)`.
- SIP rows (sip_id set) dated after the cutoff are kept on update; their units and amount are added back to the holding totals; avg_nav = invested/units, 4 dp half-up (same as the SIP poster). Cutoff = later of `statement_to` (new optional field on the commit body, sent by the web) and the latest CAS transaction date for that fund; neither → keep none. Advisor blocking fix applied: a `statement_to` after today (IST) is refused 422 "The statement date is in the future." (constant `FUTURE_STATEMENT_DATE` in services/cas_import.py); a too-early date can't double count. When the CAS has no transactions for the fund but SIP rows are kept, an opening purchase transaction (CAS units and invested, dated at the payload purchase_date) is added.
- Tests: `tests/test_cas_import*.py tests/test_sip*.py tests/test_locks.py` 123 passed. Web 389 passed at that time. The commit's lock query is inline in the router, so no `FOR UPDATE OF mutual_funds` compile test (skipped on purpose).
- The fix round was NOT re-reviewed by the advisor (one review per task rule). Re-check by reading the diff is enough.
- Docs to write (SPEC §8, §8a): SIP rows before the cutoff become plain (non-SIP) rows after an update, so the SIPs table "Instalments" and "Invested via SIP" drop after a re-import; the future-date rule; the has_sales rule.

### T2 edit guards (behaviour A) — built but NOT reviewed, one web test failing
Files: `api/app/schemas/assets.py` (closed message, "Sold in part: undo the sale to change this.", `SOLD_IN_PART_FIELDS` per type), `api/app/routers/assets.py` (PUT locks row with `with_for_update(of=model)`, checks holding_exits: closed (closed_on set or a maturity exit) → 409 {message "This holding is closed", description "Undo the sale or settlement first to change it."}; sale exit present → 422 per CHANGED protected field with loc ("body", field), unchanged values pass), `api/tests/test_edit_guards.py` (new, passing), web `components/forms/schema.ts` (mirrored constants), `lib/edit-guards.ts` + `lib/edit-guards.test.ts` (new), `components/forms/form-disabled.tsx` (ReadOnlyFieldsContext), `components/forms/fields.tsx` (TextField and DateField show read-only with helper text), `components/portfolio/edit-dialog.tsx`, `components/portfolio/grid/row-actions.tsx` and `components/holding-detail/holding-detail.tsx` (Edit hidden when closed).
- Decision made by the builder: no new `sold_in_part` API field; the web derives it from `exit.kind`, `settled`, `closed_on`, `status` already on grid/detail items. Verify this is correct for a PARTLY sold holding (partial sale has an exit but closed_on is null) — check the items actually carry the exit info the helper needs.
- TO DO 1: `web/lib/edit-guards.test.ts` fails: `lib/edit-guards.ts` imports `components/forms/schema`, which imports `@/lib/paid-from`, and vitest has no `@` alias. Fix: make `lib/edit-guards.ts` dependency-free (move `SOLD_IN_PART_FIELDS` there, keep `SOLD_IN_PART_ERROR` in schema.ts) and re-run `npm test`.
- TO DO 2: add a test that pins the web constants to the API strings; check no other Edit-dialog entry point shows Edit for closed holdings (search the web for EditDialog usages, e.g. global search, dashboard).
- TO DO 3: advisor diff review of the T2 diff (data integrity): `git diff -- api/app/routers/assets.py api/app/schemas/assets.py` plus the web files. Questions: lock+re-check order in PUT, Decimal/date comparison, MF/NPS joined-load lock (`of=model`), closed detection for fd/rd/bond settle, partly-sold detection (sale exit with closed_on null), PUT race with a concurrent sale.
- Tests run: `tests/test_edit_guards.py test_paid_from.py test_soft_delete.py test_scoping.py test_duplicates.py test_other.py test_nps.py test_locks.py` 176 passed. Web: tsc and lint clean, 389 passed plus the failing edit-guards file.

### Next steps, in order
1. Send a builder (Sonnet, effort medium) to fix T2 TO DO 1 and 2. Then advisor review of T2 (TO DO 3); send blocking fixes to a builder.
2. Run the FULL suites on the stable tree: `cd api && .venv/bin/python -m pytest -q` (was 2,194 after Wave 1) and `cd web && npx tsc --noEmit && npm run lint && npm test`.
3. Commit, one per task, via `git add <paths> && git commit -F <file>` with the Co-Authored-By line: (a) lock fixes, (b) T3 CAS, (c) T2 edit guards. Group files per task exactly as listed above (paths with parentheses as globs).
4. Docs by a builder, text from the orchestrator: SPEC §4 edit rules, §8 (has_sales, statement_to, future-date rule, opening row), §8a (SIP rows kept after the statement date; instalments figures drop after a re-import), §8b (edit guards on sold/settled), §8c; AGENTS.md repo-layout lines for new files (`web/lib/cas-import.ts`, `web/lib/edit-guards.ts`, `api/tests/test_edit_guards.py`, `api/tests/test_cas_import_guards.py`, `api/tests/test_locks.py`); STATUS; HANDOFF. Commit docs.
5. Offer the user a browser check of Wave 1 (T5: add a holding with Paid From then open the Cash grid; delete and restore it; T4: a sold bond's details page, Bond payouts card with no coupons left) and Wave 2 (Edit hidden on the Closed tab and on a sold holding's details page; Edit dialog of a partly sold holding shows quantity/units/invested/price/purchase date read-only with the helper text; CAS preview badge and disabled Update Existing for a fund with a sale; SIP rows kept after a re-import). Use probe rows only (rule 5), spare ports 8010+/3010+.
6. Push only on the user's explicit OK.

### Usage note
The 5-hour window was ~90% when the user said "wind up". Resets 2026-11-08 13:40 UTC. All builders and the advisor finished; none are running.

## Resume here — 2026-11-08 (High-risk invariant fixes)

This section supersedes the "Next items" lines in the sections below.

### 0. Progress — Wave 1 DONE (2026-11-08); start Wave 2 next
- Wave 1 is built, reviewed and committed (unpushed): `567e2aa` T4 sold-bond payouts, `bd27705` T5 cash grid refresh, `adfa3b2` T1 locks. Full suites before commit: API 2,194 passed, web 384 passed (tsc + lint clean).
- T1 notes: every FOR UPDATE on a holding model uses `with_for_update(of=Model)`, because Nps and FixedDeposit have `lazy="joined"` masters and a bare FOR UPDATE on a LEFT OUTER JOIN fails on Postgres. Keep that rule in T2/T3. Undo now also locks the exit row. Tests: `api/tests/test_locks.py` (checks lock SQL on the postgresql dialect; imports fixtures from test_paid_from, test_sip, test_sip_api).
- T4 notes: the cut lives in `bond_schedule.payments()` (helper `sold_on`), so bond-schedule, Interest & TDS and inflows all use it; a coupon ON the sale date counts. A sold bond with no coupons left returns an empty payments list: check the Bond payouts card on the bond details page shows that sensibly when verifying in the browser.
- T5 notes: `staleTypes` / `markHoldingsChanged` in `web/lib/holdings-cache.ts`. Restore always marks cash stale because `GET /api/deleted` has no paid_from field (acceptable; one extra reload).
- Not browser-checked yet: T5 (add a holding with Paid From, then open the Cash grid; delete and restore it) and T4 (a sold bond's details page). The user checks UI; offer it.
- Next: Wave 2 (T2 edit guards, T3 CAS re-import) as planned below, then docs (SPEC §8, §8a, §8b, §8c, §4 edit rules; STATUS; HANDOFF), one commit per task. Push only on the user's explicit OK (4 unpushed commits: `31d02aa` docs, then the three above; the API ones trigger the prod deploy).

### 1. Next task
The user, after an invariants audit: "yes plan high first. write tests to validate the areas we touch as we go. this will help build the test suite along the way. and ensure we dont break existing functionality." Then: "i give my OK on the behavior changes A and B. build it."
The plan below is APPROVED, including behaviours A and B. Start building Wave 1 straight away; no re-planning needed.

**Testing approach.** Every task adds tests for the code it touches. Builders run their own suites. The orchestrator runs the full API suite (2,176 passing) and the web suite (381 passing) before each commit batch. API tests use an in-memory SQLite database, which ignores row locks. So test the locking fixes three ways:
- re-check-after-lock behaviour: a second or late request gets 404 or 409 and moves no money;
- assert that the queries are built `with_for_update`;
- nothing moves money twice when run in order.

Real concurrent-race tests need Postgres in the tests. That belongs to the user's parked "full testing suite + CI" work: the user will come back to it. CI currently runs no tests or lint.

**Wave 1** (3 builders in parallel, disjoint files):

*T1. Locks (gaps 1, 4, 5, 6).*
- Files: `api/app/routers/assets.py` (delete and restore only), `services/fundings.py`, `routers/exits.py`, `services/exits.py`, `services/sip.py`, plus tests.
- Changes:
  - Delete and restore lock the holding row and its funding rows FOR UPDATE, then re-check the deleted state after the lock. A second request gets 404 or 409 and moves no money.
  - Settle locks the holding the way Sell does (`routers/exits.py:151`; Sell already locks at about line 106).
  - Paid From with `from_exit_id` locks that exit row (`fundings.py:115-120`). Undo locks the same exit row, so the two serialise and re-check.
  - SIP posting (`sip.py:222-226, 276-279`) locks the fund row before reading its units.
- Tests:
  - a double delete refunds once, and a double restore debits once;
  - settle after sell is refused, and so is sell after settle;
  - Undo is refused after a reinvest;
  - a SIP post after a partial sale keeps the units right;
  - the lock queries are built `with_for_update`.

*T4. Sold bonds in Bond payouts (gap 7).*
- Files: `services/bond_schedule.py`, `routers/analytics_tax.py`, plus tests.
- Change: a bond sold via Sell (`closed_on`) stops its schedule at the sale date, with coupons up to then and no redemption. A partial sale already reduces the quantity.
- Test: for a sold bond, bond-schedule, Interest & TDS (`analytics_tax.py:197` already cuts at the sale) and inflows (`cashflows.py:122`) agree for the FY.

*T5. Cash grid refresh (gap 8).*
- Files: `web/components/forms/use-asset-form.ts:39`, `components/portfolio/portfolio.tsx:183`, `components/holding-detail/holding-detail.tsx:160`, `lib/restore-holding.ts:12`, `lib/holdings-cache.ts`, plus vitest.
- Change: a create with `paid_from`, and a delete or restore of a holding that has `paid_from`, also mark "cash" stale.
- Test: a vitest test of the helper that decides which types to mark stale.

**Wave 2** (after T1, because it shares `routers/assets.py`):

*T2. Edit guards (gap 3, behaviour A, approved).*
- Fully sold or settled holding: PUT returns 409 "This holding is closed" / "Undo the sale or settlement first to change it.", and Edit is hidden on the Closed tab.
- Partly sold: quantity, units, invested, price and purchase date are read-only, with "Sold in part: undo the sale to change this." The API returns 422 on those fields. The wording is identical in `api/app/schemas` and `web/components/forms/schema.ts`, and the Edit dialog shows those fields read-only. Name, platform and notes stay editable.
- Funds with SIP or CAS transactions but no sales: unchanged (sales use the pro-rata fallback).
- Files: `routers/assets.py` PUT, `schemas/assets.py`, web `schema.ts`, the edit dialog, plus tests.

*T3. CAS re-import (gap 2, behaviour B, approved).*
- Funds with an app-recorded sale (a `holding_exits` row): the preview marks them "Has sales recorded here", Update existing is disabled (Add as new or skip), and the API commit refuses an update for them.
- Funds with SIP instalments: an update still replaces the transactions, because the CAS has the real instalments. SIP-posted rows dated after the CAS statement date are kept, so the SIP schedule doesn't break.
- Files: `services/cas_import.py` (`save_transactions`, about lines 242-255), `routers/cas_import.py`, `schemas/cas_import.py`, web `components/forms/cas-import/preview-step.tsx`, plus tests.

**Then:**
- docs: SPEC §8, §8b, §8c and the §4 edit rules, STATUS, HANDOFF;
- commits, one per task;
- push only with the user's OK.

### 2. Work in progress, uncommitted
None after the Wave 1 commits, apart from this notes file.

### 3. Unpushed commits
- `31d02aa` Docs: capital gains, full name, grid loading and empty states. Docs only, so a push doesn't trigger the API deploy. Push only on the user's explicit OK.

### 4. Done this session (2026-11-08)
- `ac37191` Web: capital gains helpers and types
- `772b7e4` API: capital gains maths
- `b471bc3` API: capital gains endpoint
- `2ddef3b` API: bond repayments and planned sales in capital gains
- `378e8da` Web: Capital Gains tab
- `e332c9c` Web: loading and empty states in grids and lists
- `004d1c5` API: optional full name on users (migration 0031)
- `ab31f12` Web: full name and initials in the account menu
- All of the above was pushed by the user's OK and is live on prod. Deploy run 42470474055 succeeded and migration 0031 ran on prod.
- `31d02aa` docs: local only.
- An invariants audit (6 scouts) found 27 gaps, ranked; see section 8.

### 5. Decisions and user preferences learned
- **Capital gains:**
  - Bonds count at face value × quantity − invested on maturity or planned-sale dates, whether settled or not (estimated). Repayments later this FY go to "expected", outside the totals.
  - SGB maturity is tax-free.
  - Coupons stay interest, not capital gains. The tab shows a bond interest line using the same figures as the Interest & TDS "Left to pay".
  - Crypto is detected from an Other category containing "crypto": 30% flat, no set-off.
  - The equity long-term exemption popover cites Section 112A, "in both the old and new tax regimes".
- **UI:**
  - The user wants modern minimal cards like `liquidity-card.tsx`, with no full-width green bars.
  - Every empty grid keeps its toolbar and headers, with the message inside the table (saved in memory as empty-states-inside-grids; AGENTS rule 12).
  - Never show an empty message while loading: use skeleton rows on Active/Closed switches.
- **Full name:** edited via an "Edit Name" dialog from the account menu (a /settings page was declined for now). Initials are the first and last words' first letters.
- **CI:** the user explicitly wants to plan a full testing suite later (CI runs no tests or lint). Don't start it unasked.
- **"n push" was ambiguous.** Ask when a push instruction is unclear; the push to prod happened only after "push it to prod".

### 6. Tried and abandoned
None.

### 7. Open questions waiting on the user
None for the High fixes, which are approved. The full test suite and CI plan wait for the user to bring it up.

### 8. Medium and Low backlog (from the audit; next after High)
9. Undo stops cash at 0 but reports the full `cash_added` (`exits.py:779`, `routers/exits.py:242`).
10. Any IntegrityError on settle is reported as "Already settled" (`routers/exits.py:166`).
11. A partial sale can drive invested to 0, and an MF's avg_nav to 0 (`exits.py:196-208`).
12. Paid From can take cash to exactly 0, but a cash edit needs a balance above 0 (`fundings.py:128`, `schemas/assets.py:561`).
13. A SIP can attach to a sold fund (`routers/sips.py:149-157`).
14. Returns XIRR ignores partial-sale proceeds for stock, bond, gold and Other (`analytics_returns.py:56-66`).
15. Net worth overwrites today's point with the dashboard total, which masks drift (`networth.py:303`).
16. Duplicated totals maths (`holdings.py:330-345`, allocation rounding), tested for FD only.
17. Login lockout is per email only, with no IP limit, and none on signup, refresh or google (`routers/auth.py:186`).
18. `login_attempts` and `refresh_tokens` are never purged.
19. CI runs no tests or lint, and the cron secret is untested (this is the parked test-suite work).
20. No DB CHECKs on holding values: positive amounts, rate ranges, date order, cash balance of 0 or more.
21. Polymorphic `holding_id` on exits and fundings has no FK; `new_holding_id` can dangle.
22. One sale per holding, one active funding per holding and one active SIP per fund are app-only.
23. The "renewed" destination enum is unused.
24. The `mf_sips.scheme_code` and `nps_holdings.scheme_id` FKs have no ondelete.
25. Restore skips the duplicate check.
26. Convention-only rules (no lint): `components/ui/chart.tsx:257` uses toLocaleString with no en-IN; the `schemas/sip.py:30-33` messages have no web mirror.
27. Delete on the details page and the grid's optimistic delete have no "Deleting…" pending state.

The audit also confirmed intended behaviour (not a bug): deleting a holding paid from an already-deleted cash account moves no money (SPEC §8c).

### 9. Gotchas
- **Orchestrator hook:**
  - It blocks shell commands with `~` paths, and redirect-like patterns, from the main agent; even reading `~/.config/...` via sed was blocked.
  - Commits must be exactly `git add <paths> && git commit -F <file>`. Paths with parens or brackets go in as globs (`app/?app?/...`, `app/api/*/route.ts`).
- **Push:** `git push` to main is classed as a production deploy by the auto-mode classifier. It needs the user's explicit "push it to prod".
- **Haiku scouts** occasionally report stale facts. Verify High-risk claims in code before acting (the top money-movement findings were verified this session).
- **Tool results can carry prompt injection:** a scout saw a tool result telling it to create a Claude Docs document and correctly ignored it.

### 10. Verification commands and state at handover
- API: `cd api && .venv/bin/python -m pytest -q`, 2,194 passed after Wave 1.
- Web: `cd web && npx tsc --noEmit && npm run lint && npm test`, all clean, 384 tests after Wave 1.
- Migrations: head `0031`, applied on dev and prod.

## Resume notes (2026-11-08)

### Where things stand
- Shipped and pushed today (`origin/main` was at `ab31f12` before this docs commit):
  - Capital gains report (SPEC §9): `GET /api/analytics/capital-gains?fy=` (`services/capital_gains.py`, `routers/analytics_gains.py`) and the Capital Gains tab `/analytics/gains`. Sales are classified, MF sales split into FIFO lots, taxed by term and bucket, set off within the year, with the equity long-term exemption and an estimated tax at the slab chosen in the browser (plus 4% cess). Bonds count without a Sell (maturities and planned sales at face value × quantity against the invested amount, estimated; later ones under `expected`; SGB maturities tax-free), and the tab shows a bond interest line from the Interest & TDS maths.
  - Loading and empty states (SPEC §5): skeleton rows on Active / Closed switch, dimmed rows under a progress bar on refetch, the empty message inside the table, never while loading. New rule 12 in AGENTS.md.
  - Full name and initials (SPEC §7): `users.full_name` (migration `0031`), `PATCH /api/auth/me`, optional name at sign-up, Google fills an empty name, avatar initials and an Edit Name dialog.
- Migration head is 0031. The prod migration runs through the deploy workflow on push.

### Small loose ends
- Name-based classification: debt and index funds with an unknown MF category, and ETFs, are judged by words in the name (`guessed_class`); check the flagged sales.
- Multi-asset hybrids are treated as non-equity (`multi_asset` flag); their real tax depends on the equity share.
- Non-equity sales before 23 Jul 2024 with a long-term holding are listed but not computed (`old_rules`, indexation not modelled).
- Bonds that repay principal in instalments (amortising) are treated as fully repaid at maturity.
- Carry-forward of losses to later years is not tracked; grandfathering (pre-1 Feb 2018 equity) is flagged, not computed.
- `models/holding_exit.py` and the 0029 CHECK constraint still allow destination "renewed", which nothing writes any more. A later migration can drop it.
- The SPEC §8c gallery note is now documented (the 2026-11-07 loose end is closed).
- Stock sell-price auto-fill works only for dates with a stored close. Other dates ask the user to enter the price.

### Next items, in order
1. **Buy more** for existing holdings (an MF lump sum into a held fund, more shares of a held stock). Today each holding is one lot; MF has transactions. Needs a design first; show the user the plan.
2. **SIP instalments paid from a cash account** (a monthly debit when a SIP posts).
3. Parked by the user: mobile/PWA, password reset, stock import.

### Working rules for the next session
- Orchestrator mode: the main agent plans, reviews and commits; builders (Sonnet, **medium** effort per the global rules) edit; scouts and Haiku do lookups and chores. Never Opus.
- At most 3 builders in parallel, and only after file ownership is split.
- Builders never git stash, checkout or reset, and never delete web/.next.
- The user checks UI in their browser (the agent's browser pane isn't signed in).
- Live API probes use the probe account (credentials in ~/.config/wealth-track/probe.env) on port 8010; rows are named zz-probe-…; delete only those rows.
- UX first: layman wording; spell out the net worth effect (never a vague "Not tracking"); Title Case options; amber for attention (never red).

## Resume notes (2026-11-07)

### Where things stand
- Shipped and pushed today:
  - Closing holdings (SPEC §8b): Sell for stock, bond, MF, gold and Other, full or partial; Settle for matured FD, RD and bonds; Undo of the latest exit. The table is `holding_exits` (migration 0029).
  - Paid from (SPEC §8c): every Add form can say "Paid from" a cash account, which takes the invested amount off that balance. The table is `holding_fundings` (migration 0030). Soft delete refunds the amount and restore takes it again.
  - Settle and Sell money lands in a cash account. A success step offers Reinvest buttons that prefill an Add form through sessionStorage (`web/lib/reinvest.ts`). "More…" goes through the /add gallery.
  - Grids have Active / Closed tabs (fd, rd, bond, stock, mf, gold, other) with Closed On, Received and Realised Gain columns, sortable on the server. The Closed tab defaults to newest closed first.
  - The dashboard has a "matured holdings to settle" card at the top (`unsettled` in /api/dashboard).
- Migration head is 0030. The prod migration runs through the deploy workflow on push.
- Tests: 2,119 API and 348 web, all green. Both features were live-probed on the dev DB as the probe account, and the probe rows were deleted.

### Small loose ends
- SPEC §8c does not yet list the /add gallery note "Reinvesting ₹X from <account>. Pick what you bought." (web/components/add/asset-gallery.tsx).
- `models/holding_exit.py` and the 0029 CHECK constraint still allow destination "renewed", which nothing writes any more. A later migration can drop it.
- Stock sell-price auto-fill works only for dates with a stored close (month-end backfill plus daily closes for held stocks). Other dates ask the user to enter the price.
- MF holding id 20 on the probe account is soft-deleted and will be purged in 30 days.

### Next items, in order
1. **Capital gains report** (Analytics tab), built from the `holding_exits` sale rows:
   - STCG/LTCG per financial year by asset class: listed equity and equity MF (12 months; 20% / 12.5% after 23 Jul 2024, with the ₹1.25L LTCG exemption), debt MF bought on or after 1 Apr 2023 (slab), listed bonds (12 months; 12.5%), gold and Other (24 months; 12.5%), and SGBs (redemption at maturity is tax-free).
   - The estimated tax.
   - Pre-2018 grandfathering flagged, not computed.
   - FY helpers already exist in `api/app/services/analytics_tax.py` (`fy_bounds`, `available_fys`).
   - Plan it first and show the user.
2. **Buy more** for existing holdings (an MF lump sum into a held fund, more shares of a held stock). Today each holding is one lot; MF has transactions. This needs a design.
3. **SIP instalments paid from a cash account** (a monthly debit when a SIP posts).
4. Parked by the user: mobile/PWA, password reset, stock import.

### Working rules for the next session
- Orchestrator mode: the main agent plans, reviews and commits; builders (Sonnet, **medium** effort per the global rules) edit; scouts and Haiku do lookups and chores. Never Opus.
- At most 3 builders in parallel, and only after file ownership is split.
- Builders never git stash, checkout or reset, and never delete web/.next.
- The user checks UI in their browser (the agent's browser pane isn't signed in).
- Live API probes use the probe account (credentials in ~/.config/wealth-track/probe.env) on port 8010; rows are named zz-probe-…; delete only those rows.
- UX first: layman wording; spell out the net worth effect (never a vague "Not tracking"); Title Case options; amber for attention (never red).

## Latest (2026-11-03)

Everything is pushed: `origin/main` is at `af6122d`, which includes the speed-up work.

Done:
- Analytics slice 2: Growth (`GET /api/analytics/growth`), Returns (`GET /api/analytics/returns`) with the Nifty 50 index fund, FD rate and CPI benchmark, and the Performance tab (`/analytics/performance`, two columns). Top performers rank holdings held 6 months or more by yearly return. SPEC §9.
- Speed-up: `read_bind` (AUTOCOMMIT for read-only sessions on Postgres; never for writes), fewer round trips, one-query NPS start NAVs and previous NAVs.
- The benchmark is no longer fetched on requests. It is fetched on first use; the nightly AMFI import (`refresh_benchmark_history`) refreshes it.
- Migration `0027` (index tuning). Head is `0027`.
- Docs: AGENTS repo layout and rule 11 (Title Case option labels), SPEC §9, STATUS.

Verified before the speed-up commit: JSON output of overview, growth, returns, dashboard and networth history byte-identical before and after; API suite 1,755 passed.

Next (same open items as `docs/STATUS.md` "Open (analytics)"):
1. Production latency check of the analytics endpoints (Vercel pool is 5 + 3 overflow).
2. Tax tab (slice 3: interest income and TDS by bank, then capital gains), before Jan 2027.
3. Verify `api/data/cpi_india.csv` against MOSPI.

## Resume here — 2026-11-02 night (handover to a new session)

**Start by reading:** CLAUDE.md, AGENTS.md, `docs/STATUS.md`, then this section. The older sections below are history.

**State:** `main` is clean. `84d9b2a` is pushed; the commit adding these notes may not be pushed yet (check `git status -sb`). Prod migrations are at head `0026`. Nothing uncommitted, no builders running.

**Done in the last session:**
- `84d9b2a` (pushed): gold workflows fixed.
  - `gold-history-copy.yml`: the job runs in environment `production` (where `PROD_DATABASE_URL` lives).
  - `gold-backfill.yml`: job environment is `production` for target prod and `development` for dev. GitHub auto-creates `development` on the first dev run; `DEV_DATABASE_URL` is a repo secret, so dev works there. "Check secrets" picks the URL with a `case` on the target and exports it via `$GITHUB_ENV`. An empty secret fails the run; there is no fallback to dev any more.
- Prod gold history copied and verified: dry run 41466107183, then apply run 41466318346 inserted 12,864 rows. Prod `gold_rate_history` = 12,888 rows, the same as dev.
- The earlier "prod" backfill run 41460894796 actually ran on dev (the old fallback bug). Its PDF part finished; Wayback hit HTTP 429 and failed the run. Dev history was already complete, so nothing needs redoing.

**Next, in order:**
1. **Docs for the Other asset** (API `7c63cfb`, web `b429eae`; migration 0026 is live on prod). Use `git show --stat 7c63cfb b429eae` to find the files; take every fact from the code.
   - SPEC: fields, validation (including "Purchase date can't be after the value date"), valuation, net worth behaviour, endpoints. Validation wording must match `api/app/schemas/assets.py` and `web/components/forms/schema.ts` exactly.
   - STATUS: a dated 2026-11-02 entry.
   - AGENTS.md: ten asset types in "What this is", the new files in the repo layout, 0026 in the alembic list, head `0026` under Checks.
   - One commit: "Docs: Other asset". Push only with the user's OK.
2. **Global search in the top nav bar.** The user wants it exceptional. Plan only, then get approval before any builder. The plan must cover:
   - scope: which holdings fields across all ten types (names, banks/issuers, scheme names, tickers, ISINs, notes?), plus pages and actions (Add asset per type, Recently deleted, Dashboard);
   - ranking: prefix over substring, exact ticker/ISIN first, recent or high-value holdings boosted, grouped results;
   - keyboard UX: ⌘K / Ctrl+K and "/", arrows, Enter, Esc, recent searches;
   - mobile behaviour: icon in the top bar opening a full-screen sheet;
   - pending states (required everywhere), empty and no-result states, debounce;
   - API endpoint shape and indexes (trigram is already used for MF master search);
   - no native controls; result-row text that comes from the API follows the toast rule.
3. Then the full roadmap below.

**Full roadmap: every noted piece of future work, in the user's order.** The user picked four features on 2026-11-02 to build one at a time, then analytics. Show a numbered plan and get approval before each one, and lead "what next" lists with core features.

1. Soft delete: done (Recently deleted page, 30-day purge, no Undo toast).
2. "Other" asset: done (the user names it, e.g. Crypto, and enters the value by hand). Only its docs are left (item 1 above).
3. **Global search** in the top nav bar (item 2 above).
4. **Mobile optimisation and PWA** (install to home screen). The user sees many issues on phone. Start with a scout audit of every page at 375 px wide, then plan.
5. **Analytics**, from `docs/ANALYTICS.md` (an Opus research doc written 2026-11-02). **Slice 1 (Overview) has shipped (2026-11-03; SPEC §9, STATUS); slices 2 and 3 below remain.** Read §3 "Ranking and first slice" and §5 "Open questions" before planning.
   - Ranked shortlist:
     1. Asset-class allocation, with concentration as a section. This builds the class mapping: equity/debt/gold/cash, SGB counted as gold, NPS E/C/G.
     2. Maturity calendar, with a call-out for holdings that matured but are still open.
     3. Bank safety against the DICGC ₹5L limit.
     4. Net worth change split into new money vs growth.
     5. Liquidity ladder, plus emergency-fund months once monthly expenses are stored.
     6. Returns and a benchmark vs Nifty.
     7. Data health, with MF hygiene.
   - Suggested first slice: one `/analytics` "Overview" page with one endpoint, `GET /api/analytics/overview`. The pure maths goes in `services/analytics.py` with unit tests. Sections: allocation, concentration, coming up, bank safety, liquidity, a data-health strip. ANALYTICS.md breaks it into about 5 builder tasks.
   - Slice 2: net worth change waterfall, returns per class, Nifty index-fund benchmark.
   - Slice 3, before Jan 2027 (tax season): interest income and TDS by bank, then capital gains.
   - A possible prerequisite that needs the user's OK because it changes behaviour: value SGBs at grams × IBJA 999 instead of YTM accrual.
   - Open questions to ask the user before analytics (ANALYTICS.md §5):
     - tax regime (old or new);
     - senior citizen;
     - target allocation;
     - monthly expenses;
     - whether to count EPF/PPF/NPS in the main allocation;
     - hybrid funds as their own slice or split;
     - a bank link (issuer picker) for cash accounts;
     - SGB valuation;
     - a "Sell" action that records realised gains instead of deleting;
     - which benchmark, and CPI or an FD line;
     - a sidebar page or dashboard cards.
   - Deliberately not building: Sharpe/beta-style metrics, Monte Carlo, MF look-through, ITR exports, live prices (see ANALYTICS.md §4).

**Backlog the user asked to keep (side items; mention briefly, after core work):**
- Password reset and email verification: parked. There is no domain (the app is on .vercel.app). The options are a Gmail SMTP app password, or a domain plus Resend. Don't re-offer unless the user asks.
- Prune the NAV history of schemes nobody holds (SPEC §1).
- Deferred in STATUS: SIP support and per-transaction entry for manual holdings; a matured holdings view; duplicate-holding warnings; a full automated test suite.
- Small known gaps are listed in `docs/STATUS.md` under "Known gaps / small follow-ups".

**Don't offer these:**
- Stock and bond import from CDSL/NSDL CAS or broker tradebooks: parked 2026-10-31 as "not up to the mark", because there is no buy price or date across brokers.
- Motilal Oswal Midcap XIRR gap vs Groww: dropped by the user on 2026-11-02.

**Stale lines in `docs/STATUS.md` to fix with the Other docs commit:**
- Under "Next (backlog…)", the Motilal XIRR item (dropped).
- The "Gold and silver rate history before 27 Oct 2026" item: done. Dev and prod both hold 2014 to Feb 2018 and May 2022 to today.

**Small follow-up found:** the gold backfill logs "-1 rows inserted" per month (`api/app/services/gold_history.py`; rowcount is probably -1 for that statement under psycopg3). The rows are written; only the count is wrong. Optional fix plus a pytest.

**Working-mode reminders (details in CLAUDE.md and AGENTS.md):**
- Orchestrator + builders: the main session plans, reviews and commits; `builder` (Sonnet) edits, `scout` (Haiku) reads; `effort: "medium"` on every dispatch; at most 3 builders in parallel.
- A hook blocks project edits from the main agent; commits only as `git add <paths> && git commit -F <file outside the project>`, as a single command.
- Check the 5-hour usage window before each dispatch: start nothing new at 75% or more.
- Show a plan before non-trivial builds; get approval before validation or behaviour changes.
- The user click-tests the UI (the orchestrator can't log the browser pane in). Probe account `probe-ui3@example.test`; credentials in `~/.config/wealth-track/probe.env`, never printed.
- Never touch ports 3000/8000. Never push without the user's explicit OK.

## Resume here — 2026-11-02 evening — superseded by the night section above

**Uncommitted in the working tree (lint, tsc and npm test all pass; not browser-checked):**
- Web for the "Other" asset (API already pushed as 7c63cfb, migration 0026 live on prod): `other-form.tsx`, `category-field.tsx`, `grid/configs/other.tsx`, catalog group "Other" (Shapes icon), types, and wiring in asset-form, add-form-page, asset-tabs, portfolio, holding-detail, kpi-strip, shared.tsx. The user is to click-test it first.
- Form lock while saving: `components/forms/form-disabled.tsx` (FormDisabledContext / FormBusyContext); FormShell wraps the body in a disabled fieldset and provides the context; explicit `disabled` on base-ui Select, DateField, pickers, category field and the toggles; autofill paused while saving; the Edit dialog can't be dismissed mid-save; "Saving…" with a spinner; CAS buttons get spinners.
- Next: once the user OKs, commit as two commits ("Web: Other asset" and "Web: lock form fields while saving"), then docs for Other (SPEC, STATUS, AGENTS head 0026, HANDOFF), then push on the user's OK.

**Workflow bug to fix next (small):**
- `PROD_DATABASE_URL` is an **environment** secret (environment `production`), not a repo secret. Only `api-deploy.yml` declares `environment: production`.
- `gold-history-copy.yml` needs `environment: production` on its job; its dry run failed with an empty target.
- `gold-backfill.yml` with target prod silently fell back to `DEV_DATABASE_URL` (the `a && b || c` expression), so the 2026-11-02 "prod" backfill actually ran on dev. Fix: use the production environment for prod, and fail when the secret is empty; never fall back to dev.
- Then the user runs "Gold history copy (dev to prod)": a dry run first, then with apply ticked. Prod gold history is still empty until then.

**Queue after that (memory feature-queue-2026-11-02):** global search in the top bar (plan it carefully first; the user wants it exceptional) → mobile and PWA → analytics (`docs/ANALYTICS.md`).

**Standing rules learned today:**
- Every async UI action shows a pending state (spinner plus an "…ing" label, disabled, dimmed row).
- Popup menus use the compact metric (13.5px, size-3.5 icons).
- The pointer cursor is global.
- There is no Undo toast: the delete dialog explains Recently deleted and its 30 days.
- The probe account is `probe-ui3@example.test`, with credentials in `~/.config/wealth-track/probe.env` (never print them). The orchestrator can't log the browser pane in; the user tests the UI.

## Resume here — 2026-11-02 (gold history and soft delete)

### 1. Shipped
- Gold and silver rate history, all committed: `418ecae` (net worth values gold and silver at cost when no IBJA rate exists on the date or in the 7 days before), `24e4de7` (nightly gold cron fills missed dates from the homepage's HdnGold/HdnSilver fields), `3f57f1d` and `77ed1ee` (`app.jobs.gold_backfill`: ibja.co PDFs from 10 May 2022, Wayback ibjarates.com 2014-01-01 to 2018-02-14; Mar 2018 to Apr 2022 deliberately empty), `75a1ae6` (manual `gold-backfill.yml`, target dev|prod).
- Soft delete API, committed as `db6674d` (migration 0025): delete sets `deleted_at`, restore route, `GET /api/deleted`, 30-day purge (`/api/cron/purge`, `app.jobs.purge_deleted`, dev data refresh).
- Docs (SPEC, STATUS, AGENTS, this file) are uncommitted until the orchestrator commits them.

### 2. Pending
- Web soft delete is uncommitted, awaiting a browser check: delete confirm dialog explains Recently deleted and the 30-day purge (no Undo button), `/deleted` page ("Recently deleted", sidebar link), `holdings-cache` refetch of visible grids. Files: `web/lib/restore-holding.ts`, `web/components/deleted/`, `web/app/(app)/deleted/`, plus edits to the sidebar, site header, holding detail, portfolio, `use-holdings-query.ts`, `holdings-cache.ts`, `notify.ts` and `types.ts`.
- Prod: after the push (migration 0025 runs via the deploy workflow), run the Gold rate backfill workflow with target `prod`.
- Unpushed commits on `main` (8 ahead of origin at the time of writing): `418ecae`, `24e4de7`, `72fe840`, `db6674d`, `3f57f1d`, `75a1ae6`, `77ed1ee` and the NPS docs commit `9daad53`. Push only with the user's OK.

### 3. Feature queue (in order)
1. "Other" asset
2. Global search
3. Mobile / PWA
4. Analytics (`docs/ANALYTICS.md`)

## Resume here — 2026-11-01 (NPS shipped)

### 1. Shipped (all pushed to origin/main)
- NPS, ninth asset type (`nps`, Market-linked after Mutual funds): `2834677` API master and daily NAV import (migration 0023), `f501006` API holdings (migration 0024), `b9b0114` web form, grid, details page and fresh data after saves and deletes.
- `4df7b2b`: grids and dashboard keep data across route hide (stale-while-revalidate).
- Silver (`375707b`, `84935e9`, `7e539b6`) is pushed too.
- Docs for NPS (SPEC, STATUS, AGENTS, this file) are uncommitted until the orchestrator commits them.

### 2. Prod
- Migrations 0023 and 0024 run on push via the deploy workflow.
- NPS data arrives with the first `/api/cron/nps` run (Vercel 16:45 UTC nightly, or one manual trigger with CRON_SECRET by the user). Until then the NPS scheme picker is empty and NPS holdings value at contributed.

### 3. Open items
- Motilal Oswal Midcap XIRR gap (3.87% here vs 4.49% on Groww; STATUS backlog).
- Gold and silver rate history before 27 Oct 2026 (needs a historical source).
- NAV history prune for unheld schemes (MF and NPS; deferred).
- A probe login from the EPF & PPF check may still be on the dev DB. Remove only that probe account by its exact email, never the owner's.

## Resume here — 2026-11-01 (silver planning; caching WIP) — superseded by the NPS section above

This section supersedes the "Next:" lines in the older sections below.

### 1. Next task
- Silver is built, merged into the gold asset as "Gold & Silver" (design record in §8).
  - Purities: gold 999/995/916/750/585; silver 999 and 925.
  - API committed: `375707b` (rates, migration 0022) and `84935e9` (holdings, grid filter, master rate route).
  - Web (Metal select, grid Metal column, catalog title) is uncommitted, awaiting the user's browser check on localhost:3000. Then commit as "Web: Gold & Silver (metal select, grid metal column)".
- Next: NPS (the last asset in the agreed order). Plan it first.

### 2. Work in progress, uncommitted (do not revert)
Built-in client caching, with no new dependency. Two files are modified:
- **`web/components/portfolio/grid/use-holdings-query.ts`:**
  - Removed the effect whose cleanup wiped `data`/`error`/`settled` when Next (cacheComponents / React Activity) hid the route. That wipe forced the skeleton on every return.
  - `load()` now sets `refreshing` when data already exists, so a revisit shows the old rows at once with the thin progress bar while it refetches.
  - Filter/sort/page changes already kept the old rows (`settled !== qs`). The request-id guard is unchanged.
- **`web/components/dashboard/dashboard.tsx`:** a failed background refresh with data already on screen now shows `notify.error` (toast) and keeps the data. It used to swap to the error panel. Uses a `hasData` ref.
- **Status:**
  - `npm run lint`, `npx tsc --noEmit` and `npm test` (19) pass.
  - Not checked in a browser. The user needs to try Dashboard → FD → Dashboard → FD on localhost:3000; each return should be instant.
- **After the user's OK, commit as** "Web: keep grid and dashboard data across route hide (built-in stale-while-revalidate)".
- `use-holding-detail.ts` and `net-worth-chart.tsx` already kept their data, so they are unchanged.

### 3. Unpushed commits (push only on the user's explicit OK)
- `94c656d` API: EPF & PPF holdings (migration 0021)
- `4c0e720` Web: EPF & PPF asset, pill asset tabs, deposits-first order
- `f219cb3` Docs: EPF & PPF asset and pill asset tabs
- `375707b` API: silver IBJA rates and metal column (migration 0022)
- `84935e9` API: silver holdings (metal field, filter, rate auto-fill)

`origin/main` is at `aaae997`. Prod migrations run on push (api-deploy workflow), so pushing applies 0021 and 0022 to prod. Dev DB is already at 0022.

### 4. Done this session (2026-11-01)
- **EPF & PPF asset** (slug `pf`):
  - EPF/VPF/PPF; balance + simple interest since the balance date.
  - Optional "Total deposited" (`contributed`) drives gain.
  - PPF opening date, with maturity on 1 April, 15 FYs after opening.
  - A PPF is never "matured"; past maturity `extended_until` shows the current 5-year block ("Extended · till <date>").
- **Portfolio tab redesign:**
  - Compact pills with catalog icons and round green-tint count badges (`bg-primary/15 text-primary`), with a pulsing placeholder while counts load.
  - Groups Deposits (FD, RD, Cash, EPF & PPF) | Market-linked (Stocks, Mutual funds, Bonds, Gold), with a thin divider.
  - Order comes from `web/lib/asset-catalog.ts` and drives the tabs, the Add menu, the /add gallery and the /portfolio redirect.
- **Text sizes:** grid rows, totals strip, tab labels and sidebar nav (incl. the "Wealth Tracker" title) are 13.5px.

### 5. Decisions and user preferences learned
- **EPF/PPF design:** one type with a kind field; accrued-interest valuation; an optional contributions field; PPF maturity shown.
- **PPF past 15 years:** must not be "matured". It keeps earning, and contributions are allowed only via a formal extension.
- **PF form labels:** "Current balance" (hint "Passbook total, including interest") and "Total deposited" (hint "Excluding interest. EPF: employee + employer share (not EPS)"). DateField has no hint prop, so "Balance as of" has none.
- **Tabs:**
  - No "+ N more" overflow menu; show all types inline.
  - Don't dim zero-count types; they looked disabled.
  - Counts must be badges, not bare numbers.
  - Deposits come first.
  - The divider was questioned and kept, because it mirrors the Add menu's "Deposits"/"Market-linked" headings. Removing it is a one-line change if the user asks again.
- **Font size:** the user tunes it in 0.5px steps. 13px was too small; 13.5px is accepted.
- **Fetch:** the app uses plain `fetch` via `web/lib/api.ts`. The user asked fetch vs axios; we recommended staying on fetch.
- **Caching approach:** the user chose the built-in approach (keep state on routes Next keeps mounted) over a library.

### 6. Tried and abandoned
- **SWR:** it was built fully, then discarded at the user's request, in favour of the built-in approach.
  - The working tree was reset to HEAD for web/ and `swr` removed from package.json and node_modules.
  - `web/lib/networth-cache.ts` still exists and is in use.
  - There is no `lib/swr.ts` and no `swr-provider.tsx`.

### 7. Open questions waiting on the user
- **Caching WIP:** is it good to commit (§2)?
- **Silver:** answered. Merged "Gold & Silver" was chosen and is built (§1).
- **Push:** the 3 unpushed commits (§3) need the user's OK.
- **Leftover probe login** from the EPF API check (`probe-pf-…@example.com`) is in the dev DB. Never delete accounts without the user's say.

### 8. Silver: design notes (built, see §1)
- **Source:** ibjarates.com, the page `api/app/services/gold_rates.py` already scrapes, has a "Silver 999" rate. The test fixture `api/tests/fixtures/ibja_home.html` contains it (SilverDiv, "Silver Rates (PM)"). IBJA quotes silver per kg, so per gram = ÷ 1000. Gold is quoted per 10 g (÷ 10).
- **Recommended design:**
  - Keep slug `gold`, table `gold_holdings` and URLs.
  - A migration adds `metal` (gold|silver, default gold) to `gold_holdings`, and adds metal to the key of `gold_rate_latest` / `gold_rate_history`. Today their keys are purity and purity+rate_date; "999" exists for both metals.
  - The importer also stores Silver 999.
  - Silver purities: 999 (fine) and 925 (sterling), perhaps 900 and 800. IBJA publishes only 999, so lower silver purities are valued at 999 rate × purity/999.
  - The form gets a Metal select; purity options depend on the metal. Auto-fill (`/api/master/gold/rate`) needs a metal param.
  - The grid gets a Metal column and filter. The label becomes "Gold & Silver" (tab, catalog, dashboard).
  - Net worth and valuation are as for gold.
  - Silver ETFs/funds stay under Stocks/MF.
- **Gaps:** silver history starts from the first import (gold history starts 27 Oct 2026). The user is looking for a historical gold source, which may cover silver too.
- **Touchpoints for an asset change:** see the memory file `new-assets-plan.md` and the Cash commit `4cfebd7`/`1119850` pattern.
- **Gold rate code:**
  - `api/app/services/gold_rates.py` (PURITIES, parse_rates, import_rates, latest_rates, history_between, rate_on_or_before)
  - `api/app/models/gold_rate.py`, `api/app/models/gold.py`
  - `api/app/services/valuation.py` value_gold
  - `api/app/services/networth.py`
  - `api/app/routers/master.py` (gold rate)
  - `web/components/forms/gold-form.tsx`, `use-gold-rate-autofill.ts`
  - `web/components/portfolio/grid/configs/gold.tsx`

### 9. Gotchas hit this session
- **Commit hook:** commits must be exactly `git add <paths> && git commit -F <file>`, with paths relative to the shell cwd, which drifts between api/ and web/. Use absolute message-file paths.
- **Don't run `npm run build`** while the user's dev server runs; it confuses Turbopack. Use lint + tsc + tests, then the user's browser check.
- **Subagent pipe exit codes:** builders sometimes report "pass" from piped output. Re-run the checks yourself before committing.
- **Shared files force combined commits:** when two web changes touch the same files (asset-tabs, portfolio, asset-catalog), they can't be split without interactive staging, which the hook doesn't allow. Commit EPF-type work before starting unrelated UI work on the same files.

### 10. Verification state at handover
- API: `cd api && .venv/bin/python -m pytest -q` gives 449 passed.
- Web: `cd web && npm run lint && npx tsc --noEmit && npm test` all pass (19 tests).

## Resume notes — 2026-11-01 (gold, cash and EPF & PPF)

Shipped on `main`: the EPF & PPF asset in two commits, `94c656d` (API: migration `0021`, `pf_holdings`, `/api/assets/pf`, `/api/holdings/pf`, dashboard, portfolio and net worth; PPF maturity and 5-year extension blocks in `valuation.value_pf`) and `4c0e720` (web: form with the account-type rate pre-fill, grid, details page with a PPF tenure bar, and pill asset tabs in catalog order, Deposits | Market-linked).

Shipped on `main`: the Cash & Savings asset in two commits, `4cfebd7` (API: migration `0020`, `cash_holdings`, `/api/assets/cash`, `/api/holdings/cash`, dashboard, portfolio and net worth; the balance counts from its balance date) and `1119850` (web: Cash tab after Gold, add form, grid and details page without gain). Pushed together with gold.

Shipped on `main`: the Gold asset in three commits. `89d552b`: IBJA gold rates per purity (migration `0018`, `/api/cron/gold`, `app.jobs.gold_import`). `dc32a49`: gold holdings (migration `0019`), `GET /api/master/gold/rate`, gold in dashboard, portfolio and net worth. `ad7fa85`: web gold form, grid and details page; form selects open below their trigger.

Next: plan client-side data caching (planning only), then NPS. Open gap: no IBJA history before 27 Oct 2026 (STATUS backlog).

## Resume notes — 2026-10-31 (session 4)

Shipped and pushed (main at 5ba7303 plus whatever follows this note): landing hero reworked (cursor-following faint green light rays in components/landing/aurora.tsx replace the green blobs; neutral headline gradient; white primary buttons on the landing only; "Built for Indian investors" badge, footer and the duplicate hero CTA removed — auth buttons live only in the nav); expired session → any API 401 in the browser redirects to /login?next=<page> (web/lib/api.ts); FD, RD and bond pages have an Active (n) / Matured (m) switch (grid config `statusTabs`, `?status=matured`), Matured hides the active-only totals; dashboard no longer shows "+N matured". Prod migration 0016 confirmed applied (API deploy run for f3fde0a succeeded).

Verified by the user: signed-in landing/dashboard routing, MF XIRR row and grid column, dashboard Total row, add-MF hint lines, Google sign-in on a real OAuth client.

Decisions: stock/bond import (CDSL/NSDL CAS or broker tradebooks) researched and parked — CDSL/NSDL statements have no buy price or date, tradebooks need one parser per broker and miss splits/bonuses. Don't re-offer unless the user raises it.

Backlog the user asked to keep: net worth over time (daily snapshot + dashboard trend chart; highest value); Motilal Oswal Midcap XIRR gap (3.87% here vs 4.49% Groww — ask whether Groww lists all 15 txns incl. folio 91069711026); password reset + email verification (research email provider later); prune NAV history of unheld schemes.

Gotchas: the orchestrator commit hook needs paths relative to the shell's cwd (it may be web/ — use `../docs/...`), and allows only `git add … && git commit -F <file>`. Testing the 401 redirect without signing in: set a bogus non-httpOnly `wt_refresh` cookie in the browser pane, open a page — the refresh round trip takes a few seconds before the redirect.

## Resume notes — 2026-10-31 (session 3)

State: main is at 9a41aca, pushed. Since the last handoff this session shipped: CAS import for MFs (CAMS/KFintech via casparser + our own MF Central Detailed CAS parser, `api/app/services/mfcentral_cas.py`); optional CAS password; `mf_transactions` table (migration 0016, dev DB migrated; prod migrated by the deploy workflow — confirm the "API migrate and deploy" runs for f3fde0a/9a41aca succeeded with `gh run list`); MF XIRR (details page Holding section + sortable grid column, `valuation.xirr`/`mf_xirr`, `add_mf_xirr` in routers/holdings.py); dashboard Total row emphasis (100.00%); public landing page at `/` for everyone (aurora background), dashboard moved to `/dashboard`; Import CAS is the first/default tab on /add/mf with a hint line per tab.

Not yet verified in a browser (do these first):
1. Landing page after the route move: the user's dev server served stale files (old feature cards, a hydration-mismatch "1 Issue"). After a clean restart (`npm run clean` then `npm run dev`, done by the user), check: compact feature cards + one-line privacy note, no hydration error, page height ~half of the original, mobile 375px (preview table hides "Current" below sm).
2. Signed-in side (needs the user — the browser pane has no working probe login): "Open app" on `/`, sidebar/logo/breadcrumb → `/dashboard`, post-login lands on `/dashboard`, /login while signed in → `/dashboard`.
3. XIRR row on MF details and XIRR grid column; dashboard Total row; add-MF hint lines.

Pending user actions:
- Re-import the CAS with "Update existing" (dev and prod) so `mf_transactions` is filled; the user's 4 dev funds were imported before transactions were saved, so they show "from purchase date" XIRR.
- Open question: Motilal Oswal Midcap XIRR is 3.87% here vs 4.49% on Groww (Invesco 16.06, JM 0.36, Bandhan -7.96 match exactly). Not reproducible by date shift, day count, stamp duty, dropping one txn or per-folio XIRR; ask the user whether Groww lists all 15 Motilal transactions incl. the older folio 91069711026.

Offered, not accepted yet: NSDL/CDSL CAS import for stocks/bonds (no buy price in those statements); auto-redirect on 401; intraday price provider.

Gotchas learned this session:
- next.config.ts has a Turbopack rule treating every *.css (incl. *.module.css) as global CSS: CSS modules don't work, and edits appended to globals.css didn't show up in the user's running dev server. Component-scoped CSS goes in a hoisted `<style href precedence>` inside the component (see components/landing/aurora.tsx).
- Turbopack serves stale output after files are moved/deleted; ask the user for `npm run clean` + restart. A second `next dev` can't start in web/ while the user's runs (so no spare-port web server).
- Builders using `git mv`/`git rm` leave renames staged; the orchestrator hook only allows `git add <paths> && git commit -F`, so a commit sweeps up anything already staged. Check `git status` for staged entries before committing; undoing needs a builder (the hook blocks git reset, rm, cd).
- Deleted paths don't match `?`-globs; stage them by directory (e.g. `git add app components`).
- Holding item dicts serialise dates to ISO strings (portfolio.py `_item`); helpers that take dates from items must accept strings.
- Read-only checks against the dev DB: small scripts in the session scratchpad run with `api/.venv/bin/python -I <script>` (sys.path insert api/), always `db.rollback()`; never write to the shared dev DB.
- The browser pane is signed out; the users CLI uses getpass, so probe accounts can't be created non-interactively.
- Never type the user's PAN (CAS password) anywhere; never commit or copy their CAS PDFs (they live in ~/Downloads).

Read after `AGENTS.md`, `docs/STATUS.md` and `docs/SPEC.md`. This file covers what those don't: how the last session worked, what it learned the hard way, and what's next. Verify against the code before acting; update this file when you finish a chunk of work.

## Where things stand
- `origin/main` is at `779595d`. Three local commits are unpushed: `49eeb0c`, `79f548f`, `c14bd87` (bond master enrichment). Push only when the user says so. The web bond picker rating change is uncommitted (`web/components/forms/bond-form.tsx`, `web/lib/types.ts`); review and commit it separately.
- Dev DB migration head is `0012` (Google sign-in, on top of FD/RD issuer master `0011` and auth `0010`). Prod is still `0007` until the push runs the GitHub Action. Production (Vercel web + api, Neon `production` branch) is on migration `0007`. Prod masters are populated by the 2026-10-26 securities import (`GET /api/cron/securities` on Vercel, all sources fetched with no errors): `stock_master` 5,765 rows (equity 2,629, etf 355, NSE bhavcopy SME 467, BSE 5,013), `bond_master` 6,205 (debt 6,162, bhavcopy SGB 43); bhavcopy and BSE file date 2026-10-23. `CRON_SECRET` set; AMFI master loaded (14,412 schemes / 8,821 active). Daily crons: securities 14:00 UTC (19:30 IST), AMFI 16:30 UTC (22:00 IST).
- Migration head was `0007` at the start of the 2026-10-26 session (now `0009`, see above). Neon `dev` branch: the master tables are populated: `stock_master` 5,765 rows (5,384 stock + 381 etf), `bond_master` 34,284 (after the 2026-10-27 enrichment), `mf_master` 14,412. All 5 holdings tables were emptied on 2026-10-25 at the user's request (backup JSON was in that session's scratchpad, temporary). Master/market tables kept. The user may enter real holdings again — rule 5 in AGENTS.md still applies.
- API tests: `cd api && .venv/bin/python -m pytest -q` (243 passing). Add a test with every bug fix (user decision: no full suite).

## Built on 2026-10-29 (Google sign-in, auth step 2)
- Committed locally, not pushed: API `45fd893` (migration `0012` `users.google_sub`, `app/services/google_auth.py`, `POST /api/auth/google`, `api/tests/test_google_auth.py`, `pyjwt[crypto]` for RS256) and web `3c17ac3` (`app/auth/google/start` and `callback` route handlers, `lib/auth.ts` cookies, Google button in `auth-form.tsx`, `web/.env.example`). These docs are uncommitted at time of writing; review and commit them separately. API tests: 299 passing.
- Design and error texts: SPEC §7 "Sign in with Google". Setup checklist: DEPLOY §5b.
- Not tested with a real Google client. The user creates the OAuth client, sets the env vars and runs the flow. Do not sign in as the owner account from a session (AGENTS probe rule); a probe account needs an allowlisted email added as a Google test user.
- Migration `0012` is additive (nullable column and unique constraint), so the prod push is safe for the old API code. Set `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` in the Vercel projects before using it on prod; until then the button says "isn't configured".
- Known UX gap: when the session is invalid, pages show "Not authorised" with Retry instead of redirecting to `/login`.

## Built on 2026-10-28 (FD/RD issuer master)
- Uncommitted and not pushed at time of writing; review and commit separately. Backend: migration `0011` (table `fd_issuer_master`, nullable `issuer_id` FK on `fixed_deposits` and `recurring_deposits`), model, `app/services/fd_issuers.py`, `app/jobs/issuers_import.py`, `/api/master/fd-issuer*`, `/api/cron/issuers`, `api/tests/test_fd_issuers.py`. Web: `components/forms/issuer-picker.tsx`, FD and RD forms, `schema.ts`, `lib/types.ts`. Details in SPEC §1, §2, §4, §5.
- Migration `0011` is additive (new table, nullable columns), so the prod push is safe for the old API code, unlike `0010`.
- Import by hand: `cd api && .venv/bin/python -m app.jobs.issuers_import`. It prints counts, DICGC unmatched names and notes. Read the unmatched list before changing anything.
- DICGC matching is conservative on purpose (fuzzy: ratio ≥ 0.92, margin ≥ 0.05, same sheet only). Do not loosen the thresholds to raise the count; add a `dicgc_name` override in `api/data/fd_issuer_bank_aliases.csv` instead.
- NBFC/HFC list is refreshed by hand: edit `api/data/fd_issuers_nbfc_hfc.csv` (cite the source in its `source` column), then run the import.
- Known gaps: Unity Small Finance Bank is not in Razorpay's `banks.json`; RRB names are pre-amalgamation; NBFC/HFC `reg_no` empty.
- Next: Google sign-in, then password reset (STATUS "Next (auth)").

## Built on 2026-10-28 (auth step 1)
- Commits `ca3b832` (API: users and JWT auth) and `a331552` (API: holdings scoped to the signed-in user). The web auth changes (W1) and these docs are uncommitted at time of writing; review and commit them separately.
- API: `/api/auth/{signup,login,refresh,logout}` and `GET /api/auth/me` (SPEC §7). Migration `0010` adds users, refresh tokens, login attempts and `user_id` on the five holdings tables. Existing holdings go to `OWNER_EMAIL`; the migration fails clearly if holdings exist and it is unset. CLI: `python -m app.jobs.users create|set-password|deactivate|list`.
- Web: `/login`, `/signup` (password fields have a show/hide eye toggle); signed-in email and Log out live in the top-bar account menu (`components/user-menu.tsx`, right of "Add asset"), not the sidebar; cookies `wt_access` and `wt_refresh`; `lib/auth.ts` replaces `lib/session.ts`; the route handler forwards the Bearer token and refreshes it.
- Rollout is NOT done on prod. Follow `docs/DEPLOY.md` → "Auth rollout (one-time)". Risk to check first: on the push, the Action migrates prod to `0010` before the API deploy hook fires, so for a short window the old API code (no `user_id`) can fail inserts into the holdings tables. Holdings are NOT NULL on `user_id`. Expected; don't debug it, but tell the user before pushing.
- Locally, sign-in is required. Create a dev account with `cd api && .venv/bin/python -m app.jobs.users create --email <you>` (set `JWT_SECRET` in `api/.env` first).
- Live checks with other accounts: spare-port uvicorn with an `ALLOWED_EMAILS` override and probe accounts only (AGENTS gotchas). Never touch the owner's account.

## Built this session (committed, unpushed)
- Securities masters (`1732d66`, `7214d7d`, `ce1beeb`, reshaped in `8c4c85e`, `9fa98e4`): two tables from migration 0006, `stock_master` (stocks and ETFs; NSE EQUITY_L, ETF list, plus optional NSE/BSE UDiFF bhavcopy, walks back 7 days, merged by ISIN) and `bond_master` (NSE DEBT required, plus optional GB bhavcopy). `/api/master/stock`, `/api/master/stock/{id}`, `/api/master/bond`, `/api/master/bond/{id}`; `/api/cron/securities` (Vercel 19:30 IST, returns `{stocks, bonds}`) and CLI `python -m app.jobs.securities_import` (locally needs `SSL_CERT_FILE`). Stock/bond payloads take `master_id`; the server snapshots name/symbol (stock) or name/ISIN (bond). Web: generic `components/forms/master-picker.tsx` (MF scheme picker is a thin wrapper), stock and bond pickers, linked security in the edit dialog. Known data gaps are in STATUS.
- MF master table renamed `mf_schemes` → `mf_master` (migration 0007, metadata-only). API and `mutual_funds.scheme_code` unchanged.
- MF valuation at latest AMFI NAV: current = units × `mf_nav_latest` NAV for scheme-linked holdings (stale NAV still used); manual/no-NAV stay at invested. `/api/portfolio` and `/api/holdings/mf` MF items carry `nav` and `nav_date`. One extra query over held schemes, run concurrently.
- After saving the add form → `/portfolio/{type}`.
- MF grid "NAV" column after Avg NAV (visible by default, not sortable).

## Built on 2026-10-27 (committed locally, unpushed)
- `bond_master` enrichment (`49eeb0c`, `79f548f`, `c14bd87`): merged by ISIN from seeds (`api/data/sgb_tranches.csv`, `api/data/tax_free_bonds.csv`), NSDL (`api/data/nsdl_securities.csv`), NSE DEBT, NSE ratings and SGB JSON, bhavcopy GB. Migrations 0008 and 0009. Details in SPEC §1; the module docstring of `api/app/services/bond_master.py` lists the sources.
- NSDL refresh (manual, monthly suggested): download the "List of Securities" (Active) xlsx from https://www.indiabondinfo.nsdl.com → Data & Reports → Download Reports → Instrument List Reports (needs a normal browser; the site blocks automation). Run `cd api && .venv/bin/python -m app.jobs.nsdl_convert <xlsx> [--as-of YYYY-MM-DD]`, commit the regenerated CSV, push when the user agrees. The daily cron picks it up. `openpyxl` is a dev dependency only.
- Research: RBI, FBIL, CCIL, BSE debt and the NSDL API are not automatable (reCAPTCHA, encrypted APIs, 403). No free central-government master exists; DEBT.csv and the seeds cover it.
- `vercel.json` `maxDuration` is 300. The first prod import inserts about 28k bond rows (about 95 s locally).

## Built in the last session (all shipped)
- `/add` gallery (`web/lib/asset-catalog.ts`) → `/add/[type]` forms; header breadcrumb; global "Add asset" menu in the top bar (shortcut `N`), in-page "Add FD/RD/…" as secondary.
- Inset app frame (sidebar `variant="inset"`, darker frame, rounded content panel).
- Portfolio: `/portfolio` redirects to first held type; `/portfolio/[type]` with Groww-style fixed-width tabs (sliding underline, content fade), summary strip ("N active · M matured"), per-type server-side grids (`GET /api/holdings/{type}`): search, faceted + range filters, sorting, fixed 10 rows/page, column visibility per type in localStorage, eye (disabled, details page TBD) + ⋯ Edit/Delete.
- Matured holdings are closed: excluded from all totals/counts, listed in grids; payout FDs labelled ("interest paid", "over tenure", principal-only tooltip).
- MF master data: `mf_master` (static, formerly `mf_schemes`), `mf_nav_latest`, `mf_nav_history` (+ `_sync`), AMFI import (CLI + cron), scheme picker in the MF form, NAV auto-fill by purchase date (mfapi.in, cached).
- CI: `.github/workflows/api-deploy.yml` — push to `main` touching `api/` → `alembic upgrade head` on prod (env secret `PROD_DATABASE_URL` in GitHub env `production`) → Vercel deploy hook (`VERCEL_API_DEPLOY_HOOK`). Vercel git auto-deploy for api `main` is off (`api/vercel.json`). Web still auto-deploys on push.
- `npm run clean` (root) clears `web/.next`, tsbuildinfo, Python caches.

## Next candidates (ask the user which first)
1. Holding details page at `/portfolio/{type}/{id}` (flip `DETAILS_ENABLED` in `components/portfolio/grid/row-actions.tsx`).
2. Matured list from NSDL (optional source for matured bonds; not started).
3. Matured holdings view (pinned for later).
4. Prune NAV history of unheld schemes (daily cron, 7-day grace on `fetched_at`) — deferred by user (SPEC §1).
5. Integrations decisions still open with the user: NSE EOD files (grey-area ToS), CAS upload vs broker API, paid data or free only, price history depth, Account Aggregator.
6. Commit and push the pending bond rating picker change (after review and browser check).
7. Auth step 2 (Google sign-in) is built; test the real flow with the user once the OAuth client exists (DEPLOY §5b). Auth step 3: password reset and email verification (needs an email provider; ask the user which one).

## How the user works (and how the last session ran)
- Orchestrator + builders (see `CLAUDE.md` and `~/.claude/CLAUDE.md`): main session plans, briefs, reviews, verifies in the browser, commits; builders (Sonnet, effort medium) edit; Haiku for docs/chores; max 3 builders in parallel; check usage before dispatching.
- Show a plan before non-trivial builds; the user often answers with short directives — ask with clear options when a choice is genuinely theirs.
- One master table per asset class (`stock_master`, `bond_master`, `mf_master`). Don't merge asset classes into one table; the user chose this after the single `securities` design.
- Commit after review, one per task; **push only when the user says so** (they usually do: "commit and push").
- Every brief must say: exact files allowed, rules from AGENTS.md, acceptance commands, "no tests/debug code, edit only with Edit/Write, don't commit, **leave NO background processes running**".
- Concise answers; lead with the result.

## Hard-won gotchas
- **Commit hook shapes**: only `git add <paths> && git commit -F <file>` passes; no `cd`, no extra `&&` steps; paths with `(app)` / `[type]` need globs (`web/app/?app?/portfolio/?type?/page.tsx`). Write the message file to the scratchpad first. `git -C <repo> diff/status/log` is fine for read-only checks. Python one-liners and `--dry-run` are blocked for the main agent.
- **Stale dev server**: after builders move/delete files, Turbopack serves old bundles (e.g. "useEffect is not defined", module-not-found for deleted files, grids stuck on skeleton with no request). Fix: user stops `npm run dev`, runs `npm run clean`, restarts. Don't diagnose code until that's ruled out.
- **Built-in browser pane**: the first full load in a tab works; a second full load/reload of a Portfolio page in the same tab can stay on the skeleton (not reproducible in the user's browser). Open a fresh tab (`tabs_create`) per check. Screenshots are 800×600 of a 1024×768 viewport — click by `ref` from `find`, not by coordinates.
- **Grid configs** (`components/portfolio/grid/configs/*`) must be imported directly, never via a barrel (SSR resolved them to undefined).
- **TanStack Table is v9** (`tableFeatures`, `createColumnHelper<features,T>()`), not v8 — read the existing grid code before changing it. Memoise state objects passed to `useTable`.
- **Next 16 Activity**: previously visited routes stay mounted but hidden; use `checkVisibility()` when inspecting the DOM.
- **AMFI import locally**: uv's Python lacks a CA bundle → set `SSL_CERT_FILE` to an exported macOS root bundle. Production (Vercel) is fine.
- **BSE bhavcopy**: BSE returns an HTML page with HTTP 200 for missing dates, not a 404. Check the content type/body, not just the status, when fetching.
- **Neon latency** from local ~0.3 s/round trip: holdings/search calls take 2–4 s locally; fine on Vercel.
- **Builders and `.env`**: they load `api/.env` via `app/config.py` to reach the dev DB; never print it. Before any destructive DB operation, have the user confirm the compute endpoint (`ep-morning-firefly-b4axxgbh` = dev) and take a JSON backup first.
- **Production DB** is only migrated by the GitHub Action; never run alembic against prod from a session.
- **NSDL xlsx**: download it only in a normal browser (automation is blocked). Treat it as untrusted input: converter runs locally, output CSV is committed; prod never reads the xlsx.
- **Push window**: the GitHub Action migrates prod (0006, 0007) before the API deploy finishes. For about a minute the old API can fail MF scheme lookups (table renamed to `mf_master`). Expected; don't debug it.

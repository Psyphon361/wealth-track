# AGENTS.md — Wealth Tracker (prototype v1)

Guide for any AI coding agent working in this repo. Read this first, then `docs/STATUS.md` (where things stand) and `docs/SPEC.md` (exact behaviour). If anything here conflicts with the code, the code wins — verify before acting, and update these docs in the same change.

## What this is

Personal wealth tracker for one user in India (INR only). Manual entry of ten asset types — Fixed Deposits (FD), Recurring Deposits (RD), Stocks, Bonds, Mutual Funds (MF), NPS (units valued at the NPS Trust latest NAV; contributed is the invested value), Gold & Silver (gold or silver, physical or digital, valued at the IBJA per-gram rate for its metal and purity; silver 925 is derived from the 999 rate), Cash & Savings (savings and current accounts, cash in hand; valued at its balance), EPF & PPF (EPF, VPF and PPF; balance plus simple interest since its balance date), Other (crypto, property or anything else: a name, a free-text category, a current value you enter and the date it was read, with an optional amount invested and purchase date; gain only when an amount invested is set) — with a Dashboard (totals + allocation by type) and a Portfolio tab (per-asset-type tabs and grids with filters, sorting, edit/delete). Prices: stock current value = quantity × latest price (latest NSE/BSE bhavcopy close, stored nightly by the securities import); MF uses the latest AMFI NAV and NPS the latest NPS Trust NAV; a holding with no price is valued at invested.

Philosophy: build fast, small steps, verify by build/lint, curl, and browser click-through. API has pytest in `api/tests` (run `cd api && .venv/bin/python -m pytest -q`); tests are added per bug fix, there is no full suite, except that numerical code in the analytics, portfolio and dashboard APIs must have passing unit tests before commit (see rule 9).

## Repo layout (monorepo)

```
api/            FastAPI backend (Python 3.12, uv-managed venv at api/.venv)
  app/main.py           app, CORS, X-API-Key dependency, error handlers (message/description)
  app/config.py         settings from api/.env (DATABASE_URL, CORS_ORIGINS, API_KEY, CRON_SECRET, JWT_SECRET, ALLOWED_EMAILS, OWNER_EMAIL, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET)
  app/deps.py           current_user: Bearer access token → active user, else 401
  app/models/user.py, refresh_token.py, login_attempt.py  auth tables (users, refresh_tokens, login_attempts); users has an optional full_name (≤ 80, migration 0031)
  app/routers/auth.py   /api/auth: signup (optional full_name), login, google, refresh, logout, me (GET), PATCH me (save the name; clean_name holds the name rules) (SPEC §7)
  app/services/auth.py  argon2id passwords, HS256 access JWTs, rotating refresh tokens, login rate limit
  app/services/google_auth.py  Sign in with Google: code exchange (PKCE verifier), ID token verification (Google JWKS), sign-in / link / create (SPEC §7)
  app/jobs/users.py     CLI: `python -m app.jobs.users create|set-password|deactivate|list --email …`
  app/db.py             lazy SQLAlchemy engine (psycopg3, prepare_threshold=None, pool tuned for Vercel); `read_bind(db)` gives read-only sessions an AUTOCOMMIT bind on Postgres (never for writes)
  app/models/           one table per asset type (+ base.py mixin: id, notes, created_at, updated_at)
  app/models/mf_transaction.py  mf_transactions (one row per CAS-imported MF purchase or redemption, and one per SIP instalment (rows with sip_id set); FK mutual_funds, ON DELETE CASCADE; unique (sip_id, txn_date); SPEC §8, §8a)
  app/models/mf_sip.py  mf_sips (one monthly SIP: user, mutual_fund_id? (SET NULL), scheme_code, platform, amount, day_of_month 1–28, start_date, post_from, end_date?, status active|paused|stopped, last_posted_on) and mf_sip_skips (sip_id, due_date; unique); migration 0028 (SPEC §8a)
  app/services/sip.py  SIP maths and posting: due dates, next due, units after 0.005% stamp duty, first NAV on or after the due date (NAV history fetch), post_due (the only writer of SIP instalments; idempotent via last_posted_on and the (sip_id, txn_date) key); post_due_safely runs at the end of amfi.import_navall; SIPs keep running when their holding is sold, deleted or purged (SPEC §8a)
  app/schemas/sip.py  SIP create, update and skip bodies, read and result models, MF transactions page, and the SIP validation messages (shared verbatim with the web form; SPEC §8a)
  app/routers/sips.py  /api/sips: POST (create; 409 duplicate SIP unless confirm_duplicate=true), GET ?mutual_fund_id=, PUT /{id}, POST /{id}/pause, /resume, /stop, /skip, DELETE /{id}/skip/{due_date}, DELETE /{id} (SPEC §8a)
  app/models/holding_exit.py  holding_exits (one row per sale or settlement: asset_type, holding_id, kind sale|maturity, exit date, quantity, amount, cost, charges, destination cash|none, cash account link, prev_state for undo; migration 0029, SPEC §8b)
  app/services/exits.py  closing holdings: pure maths (check_sale, sale_cost, FIFO), record_sale, record_settlement and undo_exit (the only writers; they never commit), unsettled for the dashboard (SPEC §8b)
  app/schemas/exits.py  sell, settle and undo bodies, exit read models, and the closing validation messages (shared verbatim with the web forms; SPEC §8b)
  app/routers/exits.py  /api/holdings/{type}/{id}/sell and /settle, GET /api/holdings/{type}/{id}/exits, DELETE /api/exits/{id} (undo) (SPEC §8b)
  app/models/holding_funding.py  holding_fundings (money a holding was paid for from a cash account: asset_type, holding_id, cash_holding_id, amount, funded_on, from_exit_id, prev_balance_date, refunded_at; migration 0030, SPEC §8c)
  app/services/fundings.py  "Paid from": amount per type, plan (checks, no writes), apply (debit), refund (soft delete), restore, reinvested per exit, plan_edit/apply_edit (editing the cost of a Paid From holding adjusts the account; lock order holding, funding, cash), paid_from info on items with `adjustable`/`reason` (the only writer of holding_fundings; SPEC §8c)
  app/schemas/fundings.py  the paid_from body and its validation messages (shared verbatim with the web forms; SPEC §8c)
  app/services/duplicates.py  duplicate-holding match rules for POST /api/assets/{type}: same user and type, active holdings only; 409 body; ?confirm_duplicate=true adds anyway (SPEC §4 "Duplicate warnings")
  app/models/gold.py    gold_holdings (metal, form, purity, weight_grams, purchase_date, invested_amount; no master link; migrations 0019, 0022)
  app/models/gold_rate.py  gold_rate_latest (one row per metal and purity) and gold_rate_history (metal + purity + rate_date), IBJA rates per gram
  app/models/cash.py    cash_holdings (name, kind savings|current|cash|other, balance, interest_rate?, balance_date; no master link; migration 0020)
  app/models/pf.py      pf_holdings (name, kind epf|vpf|ppf, balance, balance_date, interest_rate, contributed?, opened_on? (PPF only); no master link; migration 0021)
  app/models/other.py   other_holdings (name, category (free text, ≤ 40), current_value, value_date, invested_amount?, acquired_on?; no master link; migration 0026)
  app/models/nps.py     nps_holdings (scheme_id FK → nps_master, units 4 dp, contributed, start_date; no snapshot; migration 0024)
  app/models/nps_master.py  nps_master (scheme master; PFM, tier and asset class from the name), nps_nav_latest, nps_nav_history, nps_nav_history_sync (migration 0023)
  app/schemas/assets.py Pydantic Create/Read/Result models + ALL validation rules (NPS: N1–N4 in SPEC §2)
  app/schemas/cas_import.py  CAS import preview and commit models (SPEC §8)
  app/schemas/gold.py  gold import result and rate-on-date read models
  app/schemas/messages.py, summary.py   outcome + portfolio/dashboard response models (the dashboard also returns the 1-day change: day_change, day_change_pct, day_change_as_of, from valuation.portfolio_day_change)
  app/routers/search.py + app/services/search_index.py + app/schemas/search.py  GET /api/search/index: one flat item per holding with search terms from the linked masters; ranking happens in the browser (SPEC §4)
  app/routers/assets.py CRUD for /api/assets/{fd|rd|stock|bond|mf|nps|gold|cash|pf|other} (POST takes an optional `paid_from`, SPEC §8c)
  app/routers/cas_import.py  /api/import/cas/preview (parse a CAMS/KFintech CAS PDF in memory) and /api/import/cas/commit (save the chosen MF rows, all-or-nothing) (SPEC §8)
  app/routers/portfolio.py /api/portfolio, /api/dashboard (one query per type, run concurrently)
  app/routers/networth.py + app/services/networth.py  GET /api/networth/history?range=1m|6m|1y|all: net worth over time (pure maths in services/networth.py; schema app/schemas/networth.py)
  app/routers/analytics.py  GET /api/analytics/overview: allocation, concentration, liquidity, coming up, bank safety and data health in one response (SPEC §9); GET /api/analytics/growth (SPEC §9)
  app/services/analytics.py  pure analytics maths (classification, liquidity buckets, maturities, DICGC cover, concentration flags, data health); tests in api/tests/test_analytics.py and test_analytics_api.py
  app/schemas/analytics.py  response models for the analytics overview
  app/services/analytics_growth.py  pure growth maths: net worth change split into new money and growth, by period and for the last 12 months (SPEC §9)
  app/schemas/analytics_growth.py  response models for GET /api/analytics/growth
  app/routers/analytics_returns.py  GET /api/analytics/returns: XIRR overall, per class and per type, best and worst, rates, benchmark, excluded (SPEC §9)
  app/services/analytics_returns.py  pure returns maths: cash flows per holding, group XIRR, top and bottom performers (SPEC §9)
  app/schemas/analytics_returns.py  response models for GET /api/analytics/returns
  app/services/analytics_benchmark.py  benchmark block: Nifty 50 index fund replay (UTI, scheme 120716), FD rate and CPI inflation; refresh_benchmark_history runs in the nightly AMFI import
  api/data/cpi_india.csv  India annual CPI-Combined inflation by calendar year, hand-maintained seed read by analytics_benchmark.py
  app/routers/analytics_tax.py  GET /api/analytics/tax?fy=: interest and TDS by payer for a financial year; GET /api/analytics/bond-schedule?id=: estimated bond payouts; GET /api/analytics/inflows?months=: money coming in (SPEC §9)
  app/services/analytics_tax.py  pure tax maths: FY windows, FD, RD, savings and bond coupon interest, payer thresholds, TDS estimate, TDS by class, tax-free interest (SPEC §9); tests in api/tests/test_analytics_tax.py
  app/services/bond_schedule.py  estimated payment schedule of one bond: coupons stepped back from maturity, TDS per coupon, redemption (SPEC §9); tests in api/tests/test_bond_schedule.py
  app/services/cashflows.py  money coming in: dated bond, FD and RD inflow events split into interest and principal, by month (SPEC §9); tests in api/tests/test_cashflows.py
  app/schemas/analytics_tax.py  response models for GET /api/analytics/tax and bond-schedule
  app/schemas/analytics_cashflows.py  response models for GET /api/analytics/inflows
  app/routers/analytics_gains.py  GET /api/analytics/capital-gains?fy=: sales (and bond repayments computed from the holdings) in a financial year, gains by tax bucket after set-off and the equity exemption, fixed-rate tax and slab gains, expected bond repayments, tax-free SGB redemptions, bond interest (SPEC §9)
  tests/test_edit_guards.py  PUT edit guards (closed 409, sold-in-part 422) and a check that the web constants match api/app/schemas/assets.py; tests/test_cas_import_guards.py  CAS re-import guards (has_sales, sales refusal, SIP rows kept, future statement date); tests/test_locks.py  lock SQL checks (FOR UPDATE OF on the postgresql dialect) and re-check tests (all under api/tests/; SPEC §4)
  api/tests/pg/  real-Postgres tests (marker `pg`): harness in conftest.py (throwaway wt_test_<random> database on a local cluster, `alembic upgrade head` from empty), helpers_t2.py, helpers_t3.py; test_harness.py, test_constraints_pg.py, test_search_pg.py, test_upserts_pg.py, test_locking_queries_pg.py, test_concurrency_pg.py (overlapping sessions forced with row locks; 20x loop without a flake)
  api/tests/hypothesis_profiles.py  Hypothesis profiles (dev dependency): `dev` 50 random examples, `ci` 100 derandomized (fixed seed, database=None, print_blob), `hunt` 300 random; chosen with HYPOTHESIS_PROFILE
  api/tests/test_props_*.py  property tests of the pure money maths (valuation, analytics, exits, SIP)
  api/tests/contract/  contract tests: OpenAPI snapshot (openapi.snapshot.json; refresh with `cd api && .venv/bin/python -m tests.contract.update_snapshot`), message parity, web TS types vs the API
  api/tests/stateful/  stateful money machine (Hypothesis RuleBasedStateMachine on SQLite): world.py (frozen clock, seeded stock and MF markets), machine.py, reads.py (read-side oracle: grids, portfolio, dashboard, net worth history, search and analytics agree with the ledger; runs every 5th step and in teardown, STATEFUL_READ_EVERY=N overrides), test_clock_freeze.py (the frozen clock reaches every date source), test_money_machine.py (all ten asset types incl. RD, NPS and EPF & PPF, whose cost edits move no money (rule edit_running); also cost edits of Paid From holdings: rule edit_funded moves the account by the difference, SPEC §8c "Edit"; also purge and time: days pass, the purge runs, retention and the SET NULL/cascade results are checked; also a second user: cross-user ids are refused with no effect and user 1's reads exclude their rows; double-submit rules; API delete is 409 exactly while a holding has a sale or settlement); test_known_bugs.py holds deterministic regression tests for bugs it found; api/tests/pg/test_money_machine_pg.py runs it on Postgres; api/tests/pg/test_purge_hardening_pg.py covers the purge lock order and lock timeout
  api/app/services/purge.py also: locks every type's candidates first (fixed order, cash last) with a Postgres lock_timeout; a lock timeout raises PurgeLockTimeout and /api/cron/purge answers 503
  api/scripts/preflight_delete_refund.sql  SELECT-only prod check for old deletes made while the Paid From cash account was soft-deleted (SPEC §8c "Old data")
  api/scripts/pg_test_cluster.sh  temporary local Postgres 16 cluster for the pg tests (port 5544, trust auth): `start`, `url`, `stop`
  app/services/capital_gains.py  pure capital gains maths: classification, FIFO lots for funds, term and bucket rules (23 Jul 2024 cut-off), set-off, exemption, fixed-rate tax, bond repayments (SPEC §9); tests in api/tests/test_capital_gains.py and test_capital_gains_api.py
  app/schemas/analytics_gains.py  response models for GET /api/analytics/capital-gains
  app/routers/holdings.py  /api/holdings/{type}: per-type grids, server-side search/filter/sort/paginate over valued holdings; /api/holdings/{type}/{id}: one holding + linked master (detail page, load_holding in routers/portfolio.py); /api/holdings/mf/{id}/transactions: one fund's transactions, 10 a page, with a sip flag; MF rows carry the running `sip` summary
  app/models/stock_master.py, bond_master.py, mf_master.py, fd_issuer_master.py  master tables (one per asset class, never merged); app/schemas/market_master.py read models
  app/routers/master.py  /api/master/mf: active MF scheme search (trigram) and lookup by scheme_code; /api/master/stock, /stock/{id}, /bond, /bond/{id}: securities search and lookup; /api/master/nps, /nps/{scheme_id}: NPS scheme search (scheme or PFM name, with latest NAV) and lookup; /api/master/fd-issuer, /fd-issuer/{id}: FD/RD bank and issuer search and lookup; /api/master/gold/rate?metal&purity&date: IBJA gold or silver rate on or up to 7 days before a date (gold form auto-fill); /api/master/other/categories: the user's Other categories, most used first (category field suggestions)
  app/routers/cron.py   /api/cron/amfi and /api/cron/securities: daily imports; /api/cron/nps: daily NPS NAVs; /api/cron/issuers: weekly FD/RD issuer import; /api/cron/gold: daily IBJA gold rates; bearer CRON_SECRET (no X-API-Key)
  app/services/valuation.py  all money maths (maturity, status, invested, current, gain, interest_received, xirr, mf_xirr)
  app/services/cas_import.py  CAS PDF import: casparser 1.4.1 parse in memory (file and password never stored), merge schemes across folios into MF preview rows, purchase date rule (SPEC §8)
  app/services/mfcentral_cas.py  MF Central Detailed CAS text parser (fallback when casparser can't identify the PDF; FIFO invested, opening-balance rule; SPEC §8)
  app/services/amfi.py  AMFI NAVAll.txt parser, category mapping and importer (mf_master + mf_nav_latest), plus scheme master CSV enrichment of plan/option; import_navall posts due SIP instalments at its end (services/sip.py; never fails the import)
  app/services/stock_prices.py  latest stock prices: nightly NSE/BSE bhavcopy close stored in stock_price_latest by the securities import (upsert_closes); latest_prices reads it for /api/holdings/stock, /api/portfolio and /api/dashboard
  app/models/stock_price.py  stock_price_latest (one row per stock_master id: price, prev_close, price_time, source bhavcopy, updated_at)
  app/models/stock_price_history.py  stock_price_history (master_id, trade_date, close; one close per held stock per trading day) and stock_price_history_sync (master_id, backfilled_at; one row once a stock's 12-month backfill has run)
  app/services/stock_history.py  appends the night's close for held stocks (called inside import_stocks after upsert_closes); backfill_safely runs the one-time 12-month month-end backfill (NSE bhavcopy, BSE fallback) after the cron/CLI import
  app/services/nav_history.py  mfapi.in history fetch (on demand, 10 years kept, 24 h refetch limit), daily append for held schemes, NAV on-or-before lookup
  app/services/market_files.py  shared securities download/parse/upsert helpers (fetch_sources downloads each file once)
  app/services/stock_master.py  stock_master import: NSE EQUITY_L, ETF list, UDiFF bhavcopy (SME), BSE bhavcopy; ISIN merge
  app/services/bond_master.py  bond_master import merged by ISIN from seeds, NSDL, NSE DEBT, NSE ratings/SGB JSON and bhavcopy GB (sources listed in its docstring); bond_type derivation
  app/jobs/amfi_import.py  CLI: `python -m app.jobs.amfi_import` runs the same import
  app/services/gold_rates.py  IBJA gold and silver rate import: scrapes ibjarates.com (gold AM and PM tables, per 10 g ÷ 10, PM over AM; Silver 999 per kg ÷ 1000; silver 925 derived on read), keyed by the date the page states; latest rates to gold_rate_latest, every date to gold_rate_history; rate on or before a date for valuation, net worth and the gold form
  app/services/nps.py  NPS Trust scheme master and NAV import (latest TSV, per-scheme history with background backfill; tier and asset class from the name; sources in its docstring), scheme search and lookup
  app/services/fd_issuers.py  fd_issuer_master import (Razorpay IFSC banks, DICGC insured flag, seed files; sources in its docstring), issuer search and require_issuer for FD/RD
  app/jobs/copy_holdings.py  one-off CLI: copies one user's holdings from SOURCE_DATABASE_URL to TARGET_DATABASE_URL, re-linking masters by ISIN/issuer code/scheme_code (dry run unless --apply); `--types` limits the copy to chosen asset types (e.g. `--types bond`; slugs fd, rd, stock, bond, mf, nps, gold, cash, pf, other, comma-separated)
  app/jobs/securities_import.py  CLI: `python -m app.jobs.securities_import` runs the stock and bond master imports
  app/jobs/stock_history_backfill.py  CLI: `python -m app.jobs.stock_history_backfill [--months 12]` runs the stock price history backfill for held stocks
  app/jobs/issuers_import.py  CLI: `python -m app.jobs.issuers_import` runs the FD/RD issuer master import
  app/jobs/gold_import.py  CLI: `python -m app.jobs.gold_import` runs the IBJA gold rate import
  app/services/gold_history.py  gold and silver rate history backfill into gold_rate_history (inserts missing rows only): ibja.co daily PDFs from 10 May 2022, Wayback snapshot of ibjarates.com for 2014-01-01 to 2018-02-14 (other gold purities derived by ratio); Mar 2018 to Apr 2022 is empty by design
  app/jobs/gold_backfill.py  CLI: `python -m app.jobs.gold_backfill` runs that backfill (re-runnable)
  app/services/purge.py  soft-delete retention: hard-deletes holdings soft-deleted more than 30 days ago (MF transactions go with their fund; holding_exits and holding_fundings rows of purged holdings go too)
  app/jobs/purge_deleted.py  CLI: `python -m app.jobs.purge_deleted` runs the purge
  app/routers/deleted.py, app/schemas/deleted.py  GET /api/deleted: the user's holdings deleted in the last 30 days (restore is POST /api/assets/{type}/{id}/restore in routers/assets.py; /api/cron/purge in routers/cron.py)
  app/jobs/nps_import.py  CLI: `python -m app.jobs.nps_import` runs the NPS NAV import
  app/jobs/nsdl_convert.py  local CLI (dev deps only): `python -m app.jobs.nsdl_convert <xlsx> [--as-of]` turns the NSDL "List of Securities" export into api/data/nsdl_securities.csv
  data/                 committed seed and NSDL CSVs read by the bond import: sgb_tranches.csv, tax_free_bonds.csv, nsdl_securities.csv; FD/RD issuer seeds: fd_issuer_bank_aliases.csv, fd_issuers_nbfc_hfc.csv
  alembic/versions/     0001 initial, 0002 bond face_value, 0003 MF avg_nav Numeric(14,4), 0004 mf_schemes + mf_nav_latest (mf_schemes renamed mf_master in 0007), 0005 mf_nav_history + mf_nav_history_sync, 0006 stock_master + bond_master + master_id, 0007 mf_schemes → mf_master, 0008 bond_master enrichment (issue date/price, rating, sources), 0009 bond_master NSDL fields (coupon type, frequency, issue size, ownership, mode, perpetual, status), 0010 users + refresh_tokens + login_attempts, user_id on holdings, 0011 fd_issuer_master + issuer_id on FD/RD, 0012 users.google_sub, 0013 bonds.invested_amount, 0014 stock_price_latest, 0015 mutual_funds.invested_amount, 0016 mf_transactions, 0017 stock_price_history, 0018 gold_rate_latest + gold_rate_history, 0019 gold_holdings, 0020 cash_holdings, 0021 pf_holdings, 0022 silver: metal on gold holdings and rates, 0023 NPS master and NAV tables, 0024 nps_holdings, 0025 soft delete (deleted_at on the holding tables), 0026 other_holdings, 0027 index tuning (drops the redundant (user_id) holding indexes; multi-column trigram GIN indexes for the stock, bond and MF master searches), 0028 mf_sips, mf_sip_skips, mf_transactions.sip_id, 0029 holding_exits (sales and settlements; SPEC §8b), 0030 holding_fundings ("Paid from"; SPEC §8c), 0031 users.full_name, 0032 DB check constraints and the funding unique index
  api/scripts/invariants.sql  SELECT-only data invariant queries (orphans, funding state, cash, MF units, sale costs, constraints validated); api/scripts/check_invariants.py runs them in a READ ONLY transaction from DATABASE_URL, exit 1 on a violation (SPEC §2 "Nightly invariant check"); api/tests/pg/test_invariants_script_pg.py tests both
  api/scripts/preflight_0032.sql  SELECT-only violation counts to run on prod before migration 0032 (all must be 0; SPEC §2 "Database constraints")
  api/scripts/preflight_delete_refund.sql  SELECT-only prod check: refunded fundings whose cash account was already soft-deleted (the old delete-refund bug; SPEC §8c "Old data")
  api/tests/test_db_constraints.py  each model CHECK rejects a bad row (SQLite)
  api/tests/test_migration_0032.py  model constraint names and expressions match the migration's CHECKS
  api/tests/test_sip_sold_fund.py  SIPs for sold, deleted and purged holdings: re-pointing, no units into a sold holding, sold id on create is 422
  api/tests/test_networth_today_agreement.py  net worth history today point vs the dashboard (two strict xfails document the gold-age and stock-history drifts)
  vercel.json, .python-version, .vercelignore   Vercel (FastAPI zero-config, region iad1)
web/            Next.js 16 (App Router, TS) + Tailwind v4 + shadcn (base-ui flavour)
  AGENTS.md             Next.js 16 warning (auto-generated by next dev) — read it
  proxy.ts              Next 16 request proxy: redirects to /login without the wt_refresh cookie; /api/* without it → 401; `/` is public for everyone; /welcome redirects (308) to /; signed-in /login and /signup go to /dashboard; paths ending in a file extension (web/public files) pass
  app/(marketing)/      public landing page at / for everyone (no sidebar, no auth); the CTA buttons switch to "Open app" (/dashboard) when signed in (components/landing/auth-cta.tsx, cookie read inside Suspense)
  components/landing/   landing sections (nav, hero, product-preview, features, auth-cta, reveal); aurora.tsx renders its own hoisted <style> (keyframes) because next.config.ts's Turbopack rule treats every *.css file, including *.module.css, as global CSS (CSS modules don't work)
  app/(app)/            pages with sidebar shell: /dashboard (Dashboard), /portfolio and /portfolio/[type] (per-asset grids) live in the route group app/(app)/portfolio/(grid)/ (its layout holds the asset tabs), /portfolio/[type]/[id] (holding details) sits outside that group so it has no tabs; its breadcrumb's last crumb (holding name) is set via components/breadcrumb-label.tsx (context provider in the (app) layout + useBreadcrumbLabel), /add (type gallery), /add/[type] (form; MF has two tabs, "Import CAS" (default) and "Manual entry")
  app/(auth)/login/     login page (no sidebar)
  app/(auth)/signup/    sign-up page (invite-only; no sidebar); app/(auth)/auth-form.tsx is the shared form (password form + "Continue with Google")
  app/auth/google/start/route.ts, app/auth/google/callback/route.ts  Google OAuth: start sets state + PKCE verifier (httpOnly wt_oauth); callback checks state, calls POST /api/auth/google, sets the session cookies
  app/actions/auth.ts   login/signup/logout server actions (httpOnly cookies wt_access, wt_refresh)
  app/api/[...path]/route.ts  same-origin proxy to FastAPI; adds X-API-Key server-side; forwards raw request bytes so multipart uploads (CAS PDF) work
  components/forms/     10 asset forms (nps-form.tsx + nps-scheme-picker.tsx: scheme search over /api/master/nps), shared fields (TextField w/ Indian digit grouping, DateField), zod schema.ts, master-picker.tsx (generic securities/scheme search picker), scheme-picker.tsx (MF scheme search, thin wrapper over master-picker), issuer-picker.tsx (FD/RD bank/issuer picker and "Not listed? Enter manually" toggle), use-nav-autofill.ts (MF Average NAV auto-fill from the NAV endpoint), gold-form.tsx + use-gold-rate-autofill.ts (Total invested = weight × IBJA rate), cash-form.tsx (account type, balance as of), pf-form.tsx (account type pre-fills the rate; opening date for PPF only), other-form.tsx + category-field.tsx (Other: category combobox with the user's categories, a fixed list and free entry), form-disabled.tsx (FormDisabledContext locks every field while a form saves; FormBusyContext lets a page or the Edit dialog learn the form is busy)
  components/forms/cas-import/  MF "Import CAS" tab on /add/mf: cas-import.tsx (container), upload-step.tsx (file + password), preview-step.tsx (row checkboxes, New / In portfolio badges, Update existing / Add as new choice, Import N funds)
  components/forms/sip-form.tsx  "Start a SIP" tab on /add/mf: fund picker, platform, monthly amount, SIP date, start date, "Add to" holding Select, past-instalments Yes/No (SPEC §8a)
  components/forms/day-of-month-field.tsx  SIP date picker: a trigger ("5th of every month") opens a day grid of 1–28 (SPEC §8a)
  components/forms/use-fund-holdings.ts  one cached fetch of the user's MF holdings for the SIP form's "Add to" choice, reused until holdings change (SPEC §8a)
  components/forms/duplicate-dialog.tsx  AlertDialog for a 409 "looks like a holding you already have" (DuplicateDialog, useDuplicateWarning): Cancel keeps the form filled, "Add anyway" retries with confirm_duplicate=true; rendered by form-shell.tsx, used by use-asset-form.ts (SPEC §4)
  lib/duplicates.ts  readDuplicates (the 409 duplicates list from ApiError), confirmDuplicatePath, duplicateHref (vitest tests in duplicates.test.ts)
  components/sips/sip-grid.tsx  SIPs view table on /portfolio/mf?view=sips: summary line, search, Status filter, sortable columns, paging of 10, "Start a SIP" button; built on the standard grid parts with client-side search, filter, sort and paging (SPEC §8a)
  components/sips/sip-grid-config.tsx  SIPs table columns (Fund, Status, Monthly amount, SIP date, Next instalment, Instalments, Invested via SIP, actions) (SPEC §8a)
  components/sips/sip-badge.tsx  status badge (Active, Paused, Cancelled) and the next-instalment progress line (SPEC §8a)
  components/sips/sip-actions.tsx  SIP action menu (Update SIP, Skip Next / Undo Skip, Pause SIP / Resume SIP, Cancel SIP, Delete SIP) with confirm dialogs; also used by the MF details page (SPEC §8a)
  components/exits/  closing dialogs: sell-dialog.tsx (Sell), settle-dialog.tsx (Settle), destination-field.tsx ("Where Did The Money Land?" options, net-worth effect line and the Paid From info line), reinvest.tsx (success step and Reinvest menu), use-cash-accounts.ts, use-price-autofill.ts, after-exit.ts (SPEC §8b, §8c)
  lib/exits.ts  closing helpers: labels per type, destination options, net-worth effect text, request destinations, exit list text (vitest tests in exits.test.ts; SPEC §8b)
  lib/paid-from.ts  "Paid from" helpers: labels and messages (shared with the API), amount per type, effect line, request body, read-only line (vitest tests in paid-from.test.ts; SPEC §8c)
  lib/reinvest.ts  one-shot Reinvest prefill in sessionStorage (`wt.reinvest`), taken once by the add form of that type (vitest tests in reinvest.test.ts; SPEC §8c)
  components/forms/paid-from-field.tsx  the "Paid From" select on every add form, the reinvest note, and the read-only line on the Edit dialog (SPEC §8c)
  lib/cas-import.ts  CAS preview helpers for the has_sales rules: updateBlocked (single match with sales), rowAction (forced to create), defaultSelected (blocked rows unticked), the badge and helper texts (vitest tests in cas-import.test.ts; SPEC §8)
  lib/edit-guards.ts  edit guards for closed and partly sold holdings: canEdit, isClosed, isSoldInPart, readOnlyFields, SOLD_IN_PART_FIELDS; dependency-free so vitest can import it (vitest tests in edit-guards.test.ts; SPEC §4)
  lib/delete-guard.ts  isDeleteBlocked and deleteBlockedReason: Delete is disabled for a holding with a sale or settlement, wording shared with the API (vitest tests in delete-guard.test.ts; SPEC §5)
  lib/closed.ts  Closed tab helpers: status text, received amount, realised gain, Closed On date (vitest tests in closed.test.ts; SPEC §5)
  lib/unsettled.ts  dashboard "matured holdings to settle" helpers: title, rows, Show All toggle, settle link (vitest tests in unsettled.test.ts; SPEC §5)
  components/dashboard/unsettled-prompt.tsx  "matured holdings to settle" card at the top of the dashboard (SPEC §5)
  components/holding-detail/exits-section.tsx  Sales and settlements list on the details page, with Undo on the latest exit (SPEC §8b)
  components/portfolio/grid/closed-columns.tsx  Closed tab columns: Status, Closed On, Received, Realised Gain (SPEC §5, §8b)
  components/sips/sip-edit-dialog.tsx  Update SIP dialog: monthly amount, SIP date, end date (SPEC §8a)
  components/sips/use-sips.ts  loads GET /api/sips (all, or one holding's) and reloads on demand (SPEC §8a)
  components/holding-detail/mf-sip-section.tsx, mf-transactions.tsx  MF details page: SIP section (same actions) and the paged Transactions list (SPEC §8a)
  lib/sip.ts  SIP helpers for the web: status and action labels, action menu rules, filter, sort and summary for the SIPs table, past-instalment count and months for the Start a SIP form (vitest tests; SPEC §8a)
  app/(app)/deleted/    "Recently deleted" page (/deleted, linked at the bottom of the sidebar); components/deleted/recently-deleted.tsx is the list with per-row Restore
  lib/restore-holding.ts  restoreHolding (used by the Recently deleted page)
  lib/search/  global search logic: normalize, rank (tiers and tie-breaks), static-entries (pages and actions), recents (localStorage wt.search.recent), types
  components/search/  global search UI in the top bar: global-search (trigger, shortcuts, dialog / mobile sheet), search-panel, search-rows, search-model, search-store (in-memory index, preload and refresh), use-browser
  components/user-menu.tsx  top-bar account menu right of "Add asset": avatar with initials (email initial without a name), name over email (or "Signed in as <email>"), Edit Name, Log out (fetches GET /api/me)
  components/edit-name-dialog.tsx  Your Name dialog: Full Name field with the shared rules, PATCH /api/me through apiPatch (SPEC §7)
  lib/profile.ts  name rules and messages (shared with the API's clean_name) and the avatar initials rule (vitest tests in profile.test.ts)
  components/portfolio/ asset tabs (pills; order and groups from lib/asset-catalog.ts); per-type grid configs (grid/configs/{fd,rd,stock,bond,mf,nps,gold,cash,pf,other}.tsx + shared.tsx, each with a `detail` block for the details page); generic grid (grid/: TanStack Table v9 in manual mode, toolbar, filters, pagination, row actions); edit-dialog.tsx (shared by the grid and the details page); optimistic delete
  components/holding-detail/ holding details page: shared layout for all ten types (header, KPI strip, tenure bar, sections)
  components/asset-type-icon.tsx  shared tinted asset-type icon (details page and add form)
  components/breadcrumb-label.tsx  breadcrumb label context: BreadcrumbLabelProvider (in the (app) layout) and useBreadcrumbLabel (sets the last crumb while mounted)
  components/dashboard/ hero card with net worth and stats (summary-cards.tsx), net worth chart (net-worth-chart.tsx; shadcn chart in components/ui/chart.tsx), allocation donut (allocation-card.tsx) and holdings-by-type table
  components/ui/        shadcn components (calendar.tsx has a custom inline month/year dropdown)
  lib/api.ts            fetch helpers (apiGet, apiPost, apiPut, apiPatch, apiDelete), ApiError; base URL is same-origin /api
  lib/holding-amounts.ts  bond + MF quantity / price / total helper (vitest tests in holding-amounts.test.ts)
  lib/holdings-cache.ts  version counters bumped on holding create, update, delete or CAS import (markHoldingsStale); the grid, dashboard and details page reload on the next reveal after a change
  lib/allocation.ts  dashboard donut slices: top 5 by value plus "More" when more than 6 types (allocation.test.ts)
  lib/asset-colors.ts  fixed colour per asset slug for the donut and table bars; neutral colour for "More"
  lib/dashboard-groups.ts  groups dashboard rows into Deposits, Market-linked, Other with subtotals; hides types with no holdings (dashboard-groups.test.ts)
  app/(app)/analytics/  /analytics page (sidebar "Analytics"); renders components/analytics/analytics.tsx
  components/analytics/ analytics cards: analytics.tsx (container, states, "Prices as of" footer), allocation-card, liquidity-card (style reference), bank-safety-card, coming-up-card, concentration-card, data-health-strip
  app/(app)/analytics/layout.tsx  analytics layout with the Overview · Performance · Interest & TDS · Capital Gains tabs (components/analytics/analytics-tabs.tsx)
  app/(app)/analytics/gains/page.tsx  /analytics/gains: renders components/analytics/gains.tsx (Capital Gains tab)
  components/analytics/gains.tsx  Capital Gains tab: toolbar (financial year and slab Selects), states, empty year, tax-free SGB card, footnotes
  components/analytics/gains-summary.tsx, gains-bond-interest.tsx, gains-buckets-card.tsx, gains-sales-card.tsx, gains-expected-card.tsx  Capital Gains cards: summary with estimated tax, bond interest line, gains by type of tax, sales with lots and flags, bonds expected later this year
  lib/capital-gains.ts  capital gains types, estimated tax (slab and 4% cess), holding period, term, source and flag text, bucket notes, footnotes (vitest tests in capital-gains.test.ts)
  app/(app)/analytics/performance/page.tsx  /analytics/performance: renders components/analytics/performance.tsx (two columns: growth, then returns)
  components/analytics/performance.tsx  Performance tab: growth and returns cards together
  components/analytics/growth-change-card.tsx, growth-months-card.tsx  growth cards: change in net worth split into new money and growth, and the last 12 months
  components/analytics/returns-groups-card.tsx, returns-compare-card.tsx, returns-best-worst-card.tsx, returns-excluded.tsx  returns cards: groups by class and type, comparison with the benchmark, best and worst holdings, excluded counts
  app/(app)/analytics/interest/page.tsx  /analytics/interest: renders components/analytics/tax.tsx (Interest & TDS tab)
  components/analytics/tax.tsx  Interest & TDS tab: Bond payouts first, then the toolbar (financial year and slab Selects), the summary strip, the interest-by-type card, footnotes
  components/analytics/tax-toolbar.tsx  Interest & TDS toolbar: financial year Select and slab Select (kept in the browser)
  components/analytics/tax-summary.tsx  Interest & TDS summary strip: three figures side by side (taxable interest, TDS deducted, left to pay or refund due)
  components/analytics/tax-table.tsx  Interest by type: per-type total, received vs still-to-come bar, plain-words TDS pill; expands to payers, holdings and bond payout dates
  components/analytics/top-progress.tsx  indeterminate bar along the top of a card while its section reloads
  components/analytics/use-count-up.ts  eases a number to its new value (about 600 ms; instant with reduced motion)
  lib/tax.ts  tax tab maths and copy: financial year labels, interest-by-type bars and progress text, TDS pill sentences, payers per class, coupons left, footnotes, tax on interest and left to pay or refund due, slab parsing (vitest tests in tax.test.ts)
  components/analytics/bond-schedule.tsx  Bond payouts card: next payout, monthly stacked columns with ◆ repayment markers, floating hover card beside the hovered month, by-financial-year rows (Coupons / TDS / You get) that expand to their payouts 10 at a time (Interest & TDS tab and bond details page)
  lib/bond-schedule.ts  bond payouts helpers: monthly buckets, hover summaries and card placement, shared time axis, FY ticks, next payout, per-FY totals and payout paging (vitest tests in bond-schedule.test.ts)
  components/analytics/inflows-card.tsx  Money coming in (Overview): monthly interest and principal columns, Asset type, Amount shown and Period Selects
  lib/inflows.ts  money coming in helpers: filters, month columns, totals, item links (vitest tests in inflows.test.ts)
  components/analytics/card-info.tsx  info icon after a card label, opens a popover
  components/analytics/use-analytics-section.ts  hook that loads one analytics section (loading, error and data states)
  components/charts/donut.tsx  shared donut (analytics allocation card and the dashboard allocation card)
  lib/analytics.ts      analytics endpoint path, class colours, percent text
  lib/growth.ts         growth card maths and formatting: split colours, month labels (growth.test.ts)
  lib/returns.ts        returns bar geometry: track percent and zero line (returns.test.ts)
  lib/networth-range.ts  chart maths: growth over the range (change in current − invested) and the Y axis domain (networth-range.test.ts)
  lib/asset-catalog.ts  asset-type registry (title, hint, icon, group) for the /add gallery; its order drives the portfolio tabs, the Add menu, the /add gallery and the /portfolio redirect — add new asset classes here
  lib/notify.ts         toast helpers — render API message/description only
  lib/auth.ts           server-only: auth cookie names and options, token types, safeNext, apiAuthFetch (replaces lib/session.ts)
docs/           SPEC.md (behaviour), STATUS.md (progress/open items), HANDOFF.md (session resume notes), DEPLOY.md (Vercel+Neon), PLAN.md (original plan, historical)
.github/workflows/api-deploy.yml   on push to main touching api/: API tests first (`tests` job calls ci-api.yml), then alembic upgrade head on prod (only if the tests pass), then Vercel API deploy hook
.github/workflows/ci-api.yml   reusable (workflow_call) and on pushes to non-main branches: API tests without Postgres, then `-m pg` against a postgres:16 service with REQUIRE_PG=1
.github/workflows/ci-web.yml   on pushes and PRs touching web/: next typegen, tsc, lint, vitest (Node 24); report only, not a deploy gate
.github/workflows/nightly-invariants.yml   nightly (21:00 UTC) and manual read-only invariant check of the Neon dev data (secret DEV_DATABASE_URL, contents: read only); red run on a violation
.github/workflows/gold-backfill.yml   manual gold and silver rate history backfill, target dev|prod
.github/workflows/dev-data-refresh.yml   scheduled (and manual) market-data imports (securities, AMFI, NPS, issuers, gold) and the soft-delete purge against the Neon dev branch; secret DEV_DATABASE_URL
.claude/        Claude Code agents (builder, scout) + orchestrator hook (see CLAUDE.md). `.claude/hooks/block-orchestrator-writes.py` also refuses subagents' (builders') shell edits of project files (sed -i, redirects or tee into project paths, inline Python/Node writes) and git stash, checkout, restore, reset, clean and switch; it fails open on parse errors or uncertainty
package.json    root: `npm run dev` runs api + web together (concurrently)
```

## Run locally

Prereqs: Node 20+, `uv`, a Neon Postgres connection string.

```bash
# one-time
cd api && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt && cd ..
cp api/.env.example api/.env          # then put DATABASE_URL (Neon dev branch, pooled) in api/.env
npm install && npm --prefix web install
cd api && .venv/bin/alembic upgrade head && cd ..

# every time (hot reload for both)
npm run dev        # web http://localhost:3000, API http://localhost:8000/api (docs /docs)
```

Locally sign-in is required. Set `JWT_SECRET` in `api/.env` (`openssl rand -hex 32`), then create a dev account: `cd api && .venv/bin/python -m app.jobs.users create --email <you>` (prompts for a password). Sign-up needs your email in `ALLOWED_EMAILS`; `create` does not check it. No API key is required (no API_KEY).

## Checks

- API tests (no DB): `cd api && .venv/bin/python -m pytest -q -m "not pg"` (dev deps: `uv pip install --python .venv/bin/python -r requirements-dev.txt`; SQLite).
- API tests (real Postgres, marker `pg`): `cd api && scripts/pg_test_cluster.sh start && TEST_DATABASE_URL=$(scripts/pg_test_cluster.sh url) .venv/bin/python -m pytest -q -m pg`, then `scripts/pg_test_cluster.sh stop`. Without `TEST_DATABASE_URL` the pg tests skip; `REQUIRE_PG=1` makes a missing URL a failure (exit 4). The harness creates and drops its own `wt_test_*` database on a local host only, never reads `api/.env`, never touches Neon.
- Hypothesis profile: `HYPOTHESIS_PROFILE=ci .venv/bin/python -m pytest -q -m "not pg"` (from `api/`; `ci` is what CI should mimic). Hunt for new bugs with `HYPOTHESIS_PROFILE=hunt`; the money machine also reads `STATEFUL_EXAMPLES` (default capped at 50), `STATEFUL_STEPS` (60), `STATEFUL_NO_SHRINK=1`, and on Postgres `STATEFUL_PG_EXAMPLES` (25) and `STATEFUL_PG_STEPS` (25); add `--hypothesis-seed=N` to repeat a run.
- Test failure policy: never fix app code inside a test task. Add a deterministic strict-xfail or regression test that reproduces the failure and report it; the fix is a separate, reviewed task.
- Web: `cd web && npm run lint && npm run build`
- Web unit tests: `cd web && npm test` (vitest)
- API: start on a spare port (`cd api && .venv/bin/uvicorn app.main:app --port 8010`) and curl it; stop it afterwards.
- Migrations: `cd api && .venv/bin/alembic upgrade head` / `alembic current` (head = `0032`).
- UI: click through in a browser against `npm run dev`.

## Non-negotiable rules (user-decided)

1. **No native browser/OS controls**: no `<select>`, `<option>`, `<input type="date">`, datalist etc. — including ones a library renders internally. Use themed shadcn/base-ui components (Select, Popover+Calendar, the custom calendar dropdown).
2. **Toast and error text comes from the API.** Every API outcome returns `message` + `description`; the web only renders them. Only allowed UI-authored text: network failure with no response ("Couldn't reach the server" / "Check your connection and try again.") and loading states ("Saving…", "Deleting…").3. **Validation is enforced in BOTH the API (source of truth) and the forms, with identical wording.** Change one → change the other. Shared messages live in `web/components/forms/schema.ts` and `api/app/schemas/assets.py`. Full list in `docs/SPEC.md`.
4. **Indian number formatting** (1,00,000) for money everywhere, including inputs (display only; payloads are plain numbers).
5. **The Neon `dev` branch may contain the user's real holdings** (it was emptied on 2026-10-25, but the user enters real data there). When testing: create probe rows with unique names, and modify/delete ONLY rows you created, by exact id or by matching your probe name. Never bulk-delete, never "clean up" rows you didn't create.
6. **Never touch the user's running dev servers** (ports 3000/8000). Use spare ports (8010+, 3010+) for your own test servers and stop them when done.
7. **Secrets**: never print or commit `api/.env`, connection strings, API keys, passwords. Production credentials are handled by the user only.
8. Dark theme only; compact, minimal style; Geist fonts; `num` utility (Geist sans + tabular-nums) for figures; gain/loss colours via `text-gain` / `text-loss`. Type scale: 13.5px body, 15.4px titles, 11px uppercase labels, 13.2px helper text, inputs `text-base` on phones (SPEC §5).

9. **Numerical code needs passing unit tests before commit**: the analytics, portfolio and dashboard APIs (valuation, aggregation, classification, windows, thresholds). Keep the tests up to date whenever a calculation changes.
10. **Analytics UI uses the modern minimal card style**, with `web/components/analytics/liquidity-card.tsx` as the reference: small uppercase label, headline figure and subline, one compact visual, legend rows, linked hover across visual and rows, and a themed Select (not chips) for any view switch.
11. **Dropdown and menu option labels use Title Case** ("By Asset Class", "This Month"); form options go through `titleCase` in `components/forms/fields.tsx`.
12. **Empty grids keep their toolbar and headers and show the message inside the table; never an empty message while loading.**

## Gotchas

- **Tests that need Postgres** (locks, real constraints, concurrency, search) go in `api/tests/pg/` with the `pg` marker. Never point `TEST_DATABASE_URL` at Neon; the harness refuses non-local hosts and databases not named `wt_test_`. CI gate: a red or skipped API test run stops the prod migration and deploy (`api-deploy.yml` `needs: tests`), with no bypass; the hotfix path is to fix the failure and re-run the failed jobs. The web (Vercel) deploy is not gated.
- **Model CheckConstraints** go in the `_checks` tuple (TimestampedMixin hook), because a plain `__table_args__` on a holding model would replace its `user_id`/`deleted_at` index. Add the constraint to the model AND a migration with identical names (the `test_migration_0032` pattern).

- **Next.js 16**: request interception is `proxy.ts`, `cacheComponents: true` is on (no `export const dynamic`; request-time APIs need care), read `web/AGENTS.md` and `web/node_modules/next/dist/docs/`.
- **shadcn here is the base-ui flavour**: no `asChild`; use the `render` prop or `buttonVariants()` on `Link`.
- **npm peer conflict** (@hookform/resolvers): `web/.npmrc` sets `legacy-peer-deps=true`. Keep it (Vercel needs it too).
- **Python 3.12 via uv**: system python3 is 3.9 — never use it for the API.
- **Row locks**: use `with_for_update(of=Model)` on holdings; Nps and FixedDeposit load masters with a join, and a bare FOR UPDATE would fail or lock the master (SPEC §4).
- **Dates** are `YYYY-MM-DD` strings end to end; never use `toISOString()` for the date part (timezone shift).
- **Decimals**: API serialises Decimal as JSON numbers. Money 2 dp, rates 2 dp (column 3), MF units 3 dp, MF avg_nav 4 dp, gold weight 3 dp, IBJA rate 2 dp, NPS units and NAV 4 dp.
- **Neon latency** from local dev is ~0.28 s per round trip; `/api/portfolio` ≈ 0.8 s locally. On Vercel (iad1, next to Neon us-east) it's fast.
- **Dev server stale state**: after moving files between route groups, Turbopack can serve stale output (e.g. duplicated sidebar) — restart `npm run dev`. Running `npm run build` while dev runs can also confuse it.
- **Stale dev output fix**: if `npm run dev` serves stale output, stop it, run `npm run clean`, then start `npm run dev` again.
- Root font size is 110% (`globals.css`), so all rem sizes are scaled.
- Holdings tables live inside `SidebarInset` with `min-w-0`; keep it, or wide tables overflow the page.
- **Landing CSS**: CSS modules don't work (the Turbopack rule makes every `*.css` file global). Scope landing-only CSS inside its component (e.g. `aurora.tsx`'s hoisted `<style>`).
- **Suspense in layouts**: the `(app)` layout wraps AppSidebar and SiteHeader, and the portfolio layout wraps AssetTabs, in `<Suspense>`. Needed because `/portfolio/[type]/[id]` is fully dynamic and these components call `usePathname`; keep it when editing those layouts.
- Grid config modules (`components/portfolio/grid/configs/*`) must be imported directly, not via a barrel file: a barrel resolved them to undefined during SSR and broke fresh page loads.
- **Auth probe accounts**: for live sign-up or login checks, run a spare-port uvicorn with an override, e.g. `ALLOWED_EMAILS=probe@example.com .venv/bin/uvicorn app.main:app --port 8010` (env vars beat `api/.env`), and use only probe accounts you created. Never log in as, change the password of, or deactivate the owner's account.

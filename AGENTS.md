# AGENTS.md — Wealth Tracker (prototype v1)

Guide for any AI coding agent working in this repo. Read this first, then `docs/STATUS.md` (where things stand) and `docs/SPEC.md` (exact behaviour). If anything here conflicts with the code, the code wins — verify before acting, and update these docs in the same change.

## What this is

Personal wealth tracker for one user in India (INR only). Manual entry of ten asset types — Fixed Deposits (FD), Recurring Deposits (RD), Stocks, Bonds, Mutual Funds (MF), NPS (units valued at the NPS Trust latest NAV; contributed is the invested value), Gold & Silver (gold or silver, physical or digital, valued at the IBJA per-gram rate for its metal and purity; silver 925 is derived from the 999 rate), Cash & Savings (savings and current accounts, cash in hand; valued at its balance), EPF & PPF (EPF, VPF and PPF; balance plus simple interest since its balance date), Other (crypto, property or anything else: a name, a free-text category, a current value you enter and the date it was read, with an optional amount invested and purchase date; gain only when an amount invested is set) — with a Dashboard (totals + allocation by type) and a Portfolio tab (per-asset-type tabs and grids with filters, sorting, edit/delete). Prices: stock current value = quantity × latest price (latest NSE/BSE bhavcopy close, stored nightly by the securities import); MF uses the latest AMFI NAV and NPS the latest NPS Trust NAV; a holding with no price is valued at invested.

Philosophy: build fast, small steps, verify by build/lint, curl, and browser click-through. API has pytest in `api/tests` (run `cd api && .venv/bin/python -m pytest -q`); tests are added per bug fix, there is no full suite.

## Repo layout (monorepo)

```
api/            FastAPI backend (Python 3.12, uv-managed venv at api/.venv)
  app/main.py           app, CORS, X-API-Key dependency, error handlers (message/description)
  app/config.py         settings from api/.env (DATABASE_URL, CORS_ORIGINS, API_KEY, CRON_SECRET, JWT_SECRET, ALLOWED_EMAILS, OWNER_EMAIL, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET)
  app/deps.py           current_user: Bearer access token → active user, else 401
  app/models/user.py, refresh_token.py, login_attempt.py  auth tables (users, refresh_tokens, login_attempts)
  app/routers/auth.py   /api/auth: signup, login, google, refresh, logout, me (SPEC §7)
  app/services/auth.py  argon2id passwords, HS256 access JWTs, rotating refresh tokens, login rate limit
  app/services/google_auth.py  Sign in with Google: code exchange (PKCE verifier), ID token verification (Google JWKS), sign-in / link / create (SPEC §7)
  app/jobs/users.py     CLI: `python -m app.jobs.users create|set-password|deactivate|list --email …`
  app/db.py             lazy SQLAlchemy engine (psycopg3, prepare_threshold=None, pool tuned for Vercel)
  app/models/           one table per asset type (+ base.py mixin: id, notes, created_at, updated_at)
  app/models/mf_transaction.py  mf_transactions (one row per CAS-imported MF purchase or redemption; FK mutual_funds, ON DELETE CASCADE; SPEC §8)
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
  app/schemas/messages.py, summary.py   outcome + portfolio/dashboard response models
  app/routers/assets.py CRUD for /api/assets/{fd|rd|stock|bond|mf|nps|gold|cash|pf|other}
  app/routers/cas_import.py  /api/import/cas/preview (parse a CAMS/KFintech CAS PDF in memory) and /api/import/cas/commit (save the chosen MF rows, all-or-nothing) (SPEC §8)
  app/routers/portfolio.py /api/portfolio, /api/dashboard (one query per type, run concurrently)
  app/routers/networth.py + app/services/networth.py  GET /api/networth/history?range=1m|6m|1y|all: net worth over time (pure maths in services/networth.py; schema app/schemas/networth.py)
  app/routers/holdings.py  /api/holdings/{type}: per-type grids, server-side search/filter/sort/paginate over valued holdings; /api/holdings/{type}/{id}: one holding + linked master (detail page, load_holding in routers/portfolio.py)
  app/models/stock_master.py, bond_master.py, mf_master.py, fd_issuer_master.py  master tables (one per asset class, never merged); app/schemas/market_master.py read models
  app/routers/master.py  /api/master/mf: active MF scheme search (trigram) and lookup by scheme_code; /api/master/stock, /stock/{id}, /bond, /bond/{id}: securities search and lookup; /api/master/nps, /nps/{scheme_id}: NPS scheme search (scheme or PFM name, with latest NAV) and lookup; /api/master/fd-issuer, /fd-issuer/{id}: FD/RD bank and issuer search and lookup; /api/master/gold/rate?metal&purity&date: IBJA gold or silver rate on or up to 7 days before a date (gold form auto-fill); /api/master/other/categories: the user's Other categories, most used first (category field suggestions)
  app/routers/cron.py   /api/cron/amfi and /api/cron/securities: daily imports; /api/cron/nps: daily NPS NAVs; /api/cron/issuers: weekly FD/RD issuer import; /api/cron/gold: daily IBJA gold rates; bearer CRON_SECRET (no X-API-Key)
  app/services/valuation.py  all money maths (maturity, status, invested, current, gain, interest_received, xirr, mf_xirr)
  app/services/cas_import.py  CAS PDF import: casparser 1.4.1 parse in memory (file and password never stored), merge schemes across folios into MF preview rows, purchase date rule (SPEC §8)
  app/services/mfcentral_cas.py  MF Central Detailed CAS text parser (fallback when casparser can't identify the PDF; FIFO invested, opening-balance rule; SPEC §8)
  app/services/amfi.py  AMFI NAVAll.txt parser, category mapping and importer (mf_master + mf_nav_latest), plus scheme master CSV enrichment of plan/option
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
  app/jobs/copy_holdings.py  one-off CLI: copies one user's holdings from SOURCE_DATABASE_URL to TARGET_DATABASE_URL, re-linking masters by ISIN/issuer code/scheme_code (dry run unless --apply)
  app/jobs/securities_import.py  CLI: `python -m app.jobs.securities_import` runs the stock and bond master imports
  app/jobs/stock_history_backfill.py  CLI: `python -m app.jobs.stock_history_backfill [--months 12]` runs the stock price history backfill for held stocks
  app/jobs/issuers_import.py  CLI: `python -m app.jobs.issuers_import` runs the FD/RD issuer master import
  app/jobs/gold_import.py  CLI: `python -m app.jobs.gold_import` runs the IBJA gold rate import
  app/services/gold_history.py  gold and silver rate history backfill into gold_rate_history (inserts missing rows only): ibja.co daily PDFs from 10 May 2022, Wayback snapshot of ibjarates.com for 2014-01-01 to 2018-02-14 (other gold purities derived by ratio); Mar 2018 to Apr 2022 is empty by design
  app/jobs/gold_backfill.py  CLI: `python -m app.jobs.gold_backfill` runs that backfill (re-runnable)
  app/services/purge.py  soft-delete retention: hard-deletes holdings soft-deleted more than 30 days ago (MF transactions go with their fund)
  app/jobs/purge_deleted.py  CLI: `python -m app.jobs.purge_deleted` runs the purge
  app/routers/deleted.py, app/schemas/deleted.py  GET /api/deleted: the user's holdings deleted in the last 30 days (restore is POST /api/assets/{type}/{id}/restore in routers/assets.py; /api/cron/purge in routers/cron.py)
  app/jobs/nps_import.py  CLI: `python -m app.jobs.nps_import` runs the NPS NAV import
  app/jobs/nsdl_convert.py  local CLI (dev deps only): `python -m app.jobs.nsdl_convert <xlsx> [--as-of]` turns the NSDL "List of Securities" export into api/data/nsdl_securities.csv
  data/                 committed seed and NSDL CSVs read by the bond import: sgb_tranches.csv, tax_free_bonds.csv, nsdl_securities.csv; FD/RD issuer seeds: fd_issuer_bank_aliases.csv, fd_issuers_nbfc_hfc.csv
  alembic/versions/     0001 initial, 0002 bond face_value, 0003 MF avg_nav Numeric(14,4), 0004 mf_schemes + mf_nav_latest (mf_schemes renamed mf_master in 0007), 0005 mf_nav_history + mf_nav_history_sync, 0006 stock_master + bond_master + master_id, 0007 mf_schemes → mf_master, 0008 bond_master enrichment (issue date/price, rating, sources), 0009 bond_master NSDL fields (coupon type, frequency, issue size, ownership, mode, perpetual, status), 0010 users + refresh_tokens + login_attempts, user_id on holdings, 0011 fd_issuer_master + issuer_id on FD/RD, 0012 users.google_sub, 0013 bonds.invested_amount, 0014 stock_price_latest, 0015 mutual_funds.invested_amount, 0016 mf_transactions, 0017 stock_price_history, 0018 gold_rate_latest + gold_rate_history, 0019 gold_holdings, 0020 cash_holdings, 0021 pf_holdings, 0022 silver: metal on gold holdings and rates, 0023 NPS master and NAV tables, 0024 nps_holdings, 0025 soft delete (deleted_at on the holding tables), 0026 other_holdings
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
  app/(app)/deleted/    "Recently deleted" page (/deleted, linked at the bottom of the sidebar); components/deleted/recently-deleted.tsx is the list with per-row Restore
  lib/restore-holding.ts  restoreHolding (used by the Recently deleted page)
  components/user-menu.tsx  top-bar account menu right of "Add asset": email-initial avatar, "Signed in as <email>", Log out (fetches GET /api/me)
  components/portfolio/ asset tabs (pills; order and groups from lib/asset-catalog.ts); per-type grid configs (grid/configs/{fd,rd,stock,bond,mf,nps,gold,cash,pf,other}.tsx + shared.tsx, each with a `detail` block for the details page); generic grid (grid/: TanStack Table v9 in manual mode, toolbar, filters, pagination, row actions); edit-dialog.tsx (shared by the grid and the details page); optimistic delete
  components/holding-detail/ holding details page: shared layout for all ten types (header, KPI strip, tenure bar, sections)
  components/asset-type-icon.tsx  shared tinted asset-type icon (details page and add form)
  components/breadcrumb-label.tsx  breadcrumb label context: BreadcrumbLabelProvider (in the (app) layout) and useBreadcrumbLabel (sets the last crumb while mounted)
  components/dashboard/ KPI cards, net worth chart (net-worth-chart.tsx; shadcn chart in components/ui/chart.tsx) and holdings-by-type table
  components/ui/        shadcn components (calendar.tsx has a custom inline month/year dropdown)
  lib/api.ts            fetch helpers, ApiError; base URL is same-origin /api
  lib/holding-amounts.ts  bond + MF quantity / price / total helper (vitest tests in holding-amounts.test.ts)
  lib/holdings-cache.ts  version counters bumped on holding create, update, delete or CAS import (markHoldingsStale); the grid, dashboard and details page reload on the next reveal after a change
  lib/asset-catalog.ts  asset-type registry (title, hint, icon, group) for the /add gallery; its order drives the portfolio tabs, the Add menu, the /add gallery and the /portfolio redirect — add new asset classes here
  lib/notify.ts         toast helpers — render API message/description only
  lib/auth.ts           server-only: auth cookie names and options, token types, safeNext, apiAuthFetch (replaces lib/session.ts)
docs/           SPEC.md (behaviour), STATUS.md (progress/open items), HANDOFF.md (session resume notes), DEPLOY.md (Vercel+Neon), PLAN.md (original plan, historical)
.github/workflows/api-deploy.yml   on push to main touching api/: alembic upgrade head on prod, then Vercel API deploy hook
.github/workflows/gold-backfill.yml   manual gold and silver rate history backfill, target dev|prod
.github/workflows/dev-data-refresh.yml   scheduled (and manual) market-data imports (securities, AMFI, NPS, issuers, gold) and the soft-delete purge against the Neon dev branch; secret DEV_DATABASE_URL
.claude/        Claude Code agents (builder, scout) + orchestrator hook (see CLAUDE.md)
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

- API tests: `cd api && .venv/bin/python -m pytest -q` (dev deps: `uv pip install --python .venv/bin/python -r requirements-dev.txt`; no DB needed).
- Web: `cd web && npm run lint && npm run build`
- Web unit tests: `cd web && npm test` (vitest)
- API: start on a spare port (`cd api && .venv/bin/uvicorn app.main:app --port 8010`) and curl it; stop it afterwards.
- Migrations: `cd api && .venv/bin/alembic upgrade head` / `alembic current` (head = `0026`).
- UI: click through in a browser against `npm run dev`.

## Non-negotiable rules (user-decided)

1. **No native browser/OS controls**: no `<select>`, `<option>`, `<input type="date">`, datalist etc. — including ones a library renders internally. Use themed shadcn/base-ui components (Select, Popover+Calendar, the custom calendar dropdown).
2. **Toast and error text comes from the API.** Every API outcome returns `message` + `description`; the web only renders them. Only allowed UI-authored text: network failure with no response ("Couldn't reach the server" / "Check your connection and try again.") and loading states ("Saving…", "Deleting…").3. **Validation is enforced in BOTH the API (source of truth) and the forms, with identical wording.** Change one → change the other. Shared messages live in `web/components/forms/schema.ts` and `api/app/schemas/assets.py`. Full list in `docs/SPEC.md`.
4. **Indian number formatting** (1,00,000) for money everywhere, including inputs (display only; payloads are plain numbers).
5. **The Neon `dev` branch may contain the user's real holdings** (it was emptied on 2026-10-25, but the user enters real data there). When testing: create probe rows with unique names, and modify/delete ONLY rows you created, by exact id or by matching your probe name. Never bulk-delete, never "clean up" rows you didn't create.
6. **Never touch the user's running dev servers** (ports 3000/8000). Use spare ports (8010+, 3010+) for your own test servers and stop them when done.
7. **Secrets**: never print or commit `api/.env`, connection strings, API keys, passwords. Production credentials are handled by the user only.
8. Dark theme only; compact, minimal style; Geist fonts; `num` utility (Geist sans + tabular-nums) for figures; gain/loss colours via `text-gain` / `text-loss`.

## Gotchas

- **Next.js 16**: request interception is `proxy.ts`, `cacheComponents: true` is on (no `export const dynamic`; request-time APIs need care), read `web/AGENTS.md` and `web/node_modules/next/dist/docs/`.
- **shadcn here is the base-ui flavour**: no `asChild`; use the `render` prop or `buttonVariants()` on `Link`.
- **npm peer conflict** (@hookform/resolvers): `web/.npmrc` sets `legacy-peer-deps=true`. Keep it (Vercel needs it too).
- **Python 3.12 via uv**: system python3 is 3.9 — never use it for the API.
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

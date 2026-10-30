# AGENTS.md — Wealth Tracker (prototype v1)

Guide for any AI coding agent working in this repo. Read this first, then `docs/STATUS.md` (where things stand) and `docs/SPEC.md` (exact behaviour). If anything here conflicts with the code, the code wins — verify before acting, and update these docs in the same change.

## What this is

Personal wealth tracker for one user in India (INR only). Manual entry of five asset types — Fixed Deposits (FD), Recurring Deposits (RD), Stocks, Bonds, Mutual Funds (MF) — with a Dashboard (totals + allocation by type) and a Portfolio tab (per-asset-type tabs and grids with filters, sorting, edit/delete). Prices: stock current value = quantity × latest price (latest NSE/BSE bhavcopy close, stored nightly by the securities import); MF uses the latest AMFI NAV; a holding with no price is valued at invested.

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
  app/schemas/assets.py Pydantic Create/Read/Result models + ALL validation rules
  app/schemas/messages.py, summary.py   outcome + portfolio/dashboard response models
  app/routers/assets.py CRUD for /api/assets/{fd|rd|stock|bond|mf}
  app/routers/portfolio.py /api/portfolio, /api/dashboard (5 type queries run concurrently)
  app/routers/holdings.py  /api/holdings/{type}: per-type grids, server-side search/filter/sort/paginate over valued holdings; /api/holdings/{type}/{id}: one holding + linked master (detail page, load_holding in routers/portfolio.py)
  app/models/stock_master.py, bond_master.py, mf_master.py, fd_issuer_master.py  master tables (one per asset class, never merged); app/schemas/market_master.py read models
  app/routers/master.py  /api/master/mf: active MF scheme search (trigram) and lookup by scheme_code; /api/master/stock, /stock/{id}, /bond, /bond/{id}: securities search and lookup; /api/master/fd-issuer, /fd-issuer/{id}: FD/RD bank and issuer search and lookup
  app/routers/cron.py   /api/cron/amfi and /api/cron/securities: daily imports; /api/cron/issuers: weekly FD/RD issuer import; bearer CRON_SECRET (no X-API-Key)
  app/services/valuation.py  all money maths (maturity, status, invested, current, gain, interest_received)
  app/services/amfi.py  AMFI NAVAll.txt parser, category mapping and importer (mf_master + mf_nav_latest)
  app/services/stock_prices.py  latest stock prices: nightly NSE/BSE bhavcopy close stored in stock_price_latest by the securities import (upsert_closes); latest_prices reads it for /api/holdings/stock, /api/portfolio and /api/dashboard
  app/models/stock_price.py  stock_price_latest (one row per stock_master id: price, prev_close, price_time, source bhavcopy, updated_at)
  app/services/nav_history.py  mfapi.in history fetch (on demand, 10 years kept, 24 h refetch limit), daily append for held schemes, NAV on-or-before lookup
  app/services/market_files.py  shared securities download/parse/upsert helpers (fetch_sources downloads each file once)
  app/services/stock_master.py  stock_master import: NSE EQUITY_L, ETF list, UDiFF bhavcopy (SME), BSE bhavcopy; ISIN merge
  app/services/bond_master.py  bond_master import merged by ISIN from seeds, NSDL, NSE DEBT, NSE ratings/SGB JSON and bhavcopy GB (sources listed in its docstring); bond_type derivation
  app/jobs/amfi_import.py  CLI: `python -m app.jobs.amfi_import` runs the same import
  app/services/fd_issuers.py  fd_issuer_master import (Razorpay IFSC banks, DICGC insured flag, seed files; sources in its docstring), issuer search and require_issuer for FD/RD
  app/jobs/copy_holdings.py  one-off CLI: copies one user's holdings from SOURCE_DATABASE_URL to TARGET_DATABASE_URL, re-linking masters by ISIN/issuer code/scheme_code (dry run unless --apply)
  app/jobs/securities_import.py  CLI: `python -m app.jobs.securities_import` runs the stock and bond master imports
  app/jobs/issuers_import.py  CLI: `python -m app.jobs.issuers_import` runs the FD/RD issuer master import
  app/jobs/nsdl_convert.py  local CLI (dev deps only): `python -m app.jobs.nsdl_convert <xlsx> [--as-of]` turns the NSDL "List of Securities" export into api/data/nsdl_securities.csv
  data/                 committed seed and NSDL CSVs read by the bond import: sgb_tranches.csv, tax_free_bonds.csv, nsdl_securities.csv; FD/RD issuer seeds: fd_issuer_bank_aliases.csv, fd_issuers_nbfc_hfc.csv
  alembic/versions/     0001 initial, 0002 bond face_value, 0003 MF avg_nav Numeric(14,4), 0004 mf_schemes + mf_nav_latest (mf_schemes renamed mf_master in 0007), 0005 mf_nav_history + mf_nav_history_sync, 0006 stock_master + bond_master + master_id, 0007 mf_schemes → mf_master, 0008 bond_master enrichment (issue date/price, rating, sources), 0009 bond_master NSDL fields (coupon type, frequency, issue size, ownership, mode, perpetual, status), 0010 users + refresh_tokens + login_attempts, user_id on holdings, 0011 fd_issuer_master + issuer_id on FD/RD, 0012 users.google_sub, 0013 bonds.invested_amount, 0014 stock_price_latest
  vercel.json, .python-version, .vercelignore   Vercel (FastAPI zero-config, region iad1)
web/            Next.js 16 (App Router, TS) + Tailwind v4 + shadcn (base-ui flavour)
  AGENTS.md             Next.js 16 warning (auto-generated by next dev) — read it
  proxy.ts              Next 16 request proxy: redirects to /login without the wt_refresh cookie; /api/* without it → 401
  app/(app)/            pages with sidebar shell: / (Dashboard), /portfolio and /portfolio/[type] (per-asset grids) live in the route group app/(app)/portfolio/(grid)/ (its layout holds the asset tabs), /portfolio/[type]/[id] (holding details) sits outside that group so it has no tabs; its breadcrumb's last crumb (holding name) is set via components/breadcrumb-label.tsx (context provider in the (app) layout + useBreadcrumbLabel), /add (type gallery), /add/[type] (form)
  app/(auth)/login/     login page (no sidebar)
  app/(auth)/signup/    sign-up page (invite-only; no sidebar); app/(auth)/auth-form.tsx is the shared form (password form + "Continue with Google")
  app/auth/google/start/route.ts, app/auth/google/callback/route.ts  Google OAuth: start sets state + PKCE verifier (httpOnly wt_oauth); callback checks state, calls POST /api/auth/google, sets the session cookies
  app/actions/auth.ts   login/signup/logout server actions (httpOnly cookies wt_access, wt_refresh)
  app/api/[...path]/route.ts  same-origin proxy to FastAPI; adds X-API-Key server-side
  components/forms/     5 asset forms, shared fields (TextField w/ Indian digit grouping, DateField), zod schema.ts, master-picker.tsx (generic securities/scheme search picker), scheme-picker.tsx (MF scheme search, thin wrapper over master-picker), issuer-picker.tsx (FD/RD bank/issuer picker and "Not listed? Enter manually" toggle), use-nav-autofill.ts (MF Average NAV auto-fill from the NAV endpoint)
  components/user-menu.tsx  top-bar account menu right of "Add asset": email-initial avatar, "Signed in as <email>", Log out (fetches GET /api/me)
  components/portfolio/ asset tabs; per-type grid configs (grid/configs/{fd,rd,stock,bond,mf}.tsx + shared.tsx, each with a `detail` block for the details page); generic grid (grid/: TanStack Table v9 in manual mode, toolbar, filters, pagination, row actions); edit-dialog.tsx (shared by the grid and the details page); optimistic delete
  components/holding-detail/ holding details page: shared layout for all five types (header, KPI strip, tenure bar, sections)
  components/asset-type-icon.tsx  shared tinted asset-type icon (details page and add form)
  components/breadcrumb-label.tsx  breadcrumb label context: BreadcrumbLabelProvider (in the (app) layout) and useBreadcrumbLabel (sets the last crumb while mounted)
  components/dashboard/ KPI cards + holdings-by-type table
  components/ui/        shadcn components (calendar.tsx has a custom inline month/year dropdown)
  lib/api.ts            fetch helpers, ApiError; base URL is same-origin /api
  lib/bond-amounts.ts   bond quantity / price / total helper (vitest tests in bond-amounts.test.ts)
  lib/asset-catalog.ts  asset-type registry (title, hint, icon, group) for the /add gallery — add new asset classes here
  lib/notify.ts         toast helpers — render API message/description only
  lib/auth.ts           server-only: auth cookie names and options, token types, safeNext, apiAuthFetch (replaces lib/session.ts)
docs/           SPEC.md (behaviour), STATUS.md (progress/open items), HANDOFF.md (session resume notes), DEPLOY.md (Vercel+Neon), PLAN.md (original plan, historical)
.github/workflows/api-deploy.yml   on push to main touching api/: alembic upgrade head on prod, then Vercel API deploy hook
.github/workflows/dev-data-refresh.yml   scheduled (and manual) market-data imports (securities, AMFI, issuers) against the Neon dev branch; secret DEV_DATABASE_URL
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
- Migrations: `cd api && .venv/bin/alembic upgrade head` / `alembic current` (head = `0014`).
- UI: click through in a browser against `npm run dev`.

## Non-negotiable rules (user-decided)

1. **No native browser/OS controls**: no `<select>`, `<option>`, `<input type="date">`, datalist etc. — including ones a library renders internally. Use themed shadcn/base-ui components (Select, Popover+Calendar, the custom calendar dropdown).
2. **Toast and error text comes from the API.** Every API outcome returns `message` + `description`; the web only renders them. Only allowed UI-authored text: network failure with no response ("Couldn't reach the server" / "Check your connection and try again.") and loading states ("Saving…", "Deleting…").
3. **Validation is enforced in BOTH the API (source of truth) and the forms, with identical wording.** Change one → change the other. Shared messages live in `web/components/forms/schema.ts` and `api/app/schemas/assets.py`. Full list in `docs/SPEC.md`.
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
- **Decimals**: API serialises Decimal as JSON numbers. Money 2 dp, rates 2 dp (column 3), MF units 3 dp, MF avg_nav 4 dp.
- **Neon latency** from local dev is ~0.28 s per round trip; `/api/portfolio` ≈ 0.8 s locally. On Vercel (iad1, next to Neon us-east) it's fast.
- **Dev server stale state**: after moving files between route groups, Turbopack can serve stale output (e.g. duplicated sidebar) — restart `npm run dev`. Running `npm run build` while dev runs can also confuse it.
- **Stale dev output fix**: if `npm run dev` serves stale output, stop it, run `npm run clean`, then start `npm run dev` again.
- Root font size is 110% (`globals.css`), so all rem sizes are scaled.
- Holdings tables live inside `SidebarInset` with `min-w-0`; keep it, or wide tables overflow the page.
- **Suspense in layouts**: the `(app)` layout wraps AppSidebar and SiteHeader, and the portfolio layout wraps AssetTabs, in `<Suspense>`. Needed because `/portfolio/[type]/[id]` is fully dynamic and these components call `usePathname`; keep it when editing those layouts.
- Grid config modules (`components/portfolio/grid/configs/*`) must be imported directly, not via a barrel file: a barrel resolved them to undefined during SSR and broke fresh page loads.
- **Auth probe accounts**: for live sign-up or login checks, run a spare-port uvicorn with an override, e.g. `ALLOWED_EMAILS=probe@example.com .venv/bin/uvicorn app.main:app --port 8010` (env vars beat `api/.env`), and use only probe accounts you created. Never log in as, change the password of, or deactivate the owner's account.

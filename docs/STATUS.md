# STATUS — handoff notes (last updated 2026-10-25)

## Done (all committed on `main`)

- v1 plan tasks 0–8: monorepo, FastAPI + Neon, 5 asset types CRUD, valuation, `/portfolio`, `/dashboard`, Next.js forms, Portfolio tab, Dashboard.
- Root `npm run dev` (api + web with hot reload).
- UI revamp: dark zinc theme, Geist, collapsible sidebar (13.5rem), compact tables/cards, themed toasts, themed date picker with custom month/year dropdowns, Indian digit grouping in inputs, root zoom 110%, no page horizontal overflow.
- Performance: concurrent per-type queries, no pool pre-ping; optimistic delete, instant edit, background refresh.
- Bond `face_value` (migration 0002); MF `avg_nav` 4 dp (migration 0003).
- Full validation rule set in API + forms with identical wording (see SPEC §2).
- Payout FD semantics (payout frequency, interest_received) (SPEC §3).
- Toast/error text sourced from API `message`/`description` (SPEC §4).
- /add redesign: grouped tile gallery (Groww-style) → per-type form page /add/[type]; legacy ?type= redirects.
- Portfolio redesign: per-asset tabs and grids (/api/holdings/{type}) with type-specific columns/filters, search, sorting, 10-row paging, column visibility saved per type, tab transition animation.
- Deployment prep: Vercel-ready API (`api/vercel.json`, region iad1, API key), password gate + same-origin proxy in web, `docs/DEPLOY.md`.
- MF master data from AMFI (mf_schemes + mf_nav_latest, daily cron, scheme picker in MF form).
- Historical NAV lookup (mf_nav_history via mfapi.in, cached) and Average NAV auto-fill in the MF form.
- MF valuation at the latest AMFI NAV (units × NAV for scheme-linked holdings; `nav`/`nav_date` in API items) (SPEC §3).
- After saving an asset, the add form opens that type's portfolio tab (`/portfolio/{type}`).
- MF grid "NAV" column (latest NAV, "as of" date).

Verified in the browser: add (FD, stock), edit (stock), delete, dashboard numbers, date picker + year dropdown, comma grouping/caret, payout form relabel, API-sourced toasts.
Verified only via API/curl or build: RD/bond/MF save through the UI, per-field validation messages in the forms, edit dialog date picker layering, 500 handler.

## Deployment state

- GitHub: https://github.com/Psyphon361/wealth-track (`origin`, branch `main`). Check `git log origin/main..main` for unpushed commits.
- Vercel: user created two projects (root `api/` and root `web/`). Web is live at https://wealth-track-nu.vercel.app — login gate works (unauthenticated `/api/dashboard` → 401, `/` → redirect to /login).
- Production (as of 2026-10-25): migrations ran via the GitHub Action; the production DB is at `0005` (it had been at `0002`, so `0003` is now applied too). `CRON_SECRET` is set. The first AMFI import succeeded (14412 schemes, 8821 active) and the daily cron (22:00 IST) is live. The earlier 404 on `/api/dashboard` after login was fixed. GitHub secrets (`PROD_DATABASE_URL` as a `production` environment secret, `VERCEL_API_DEPLOY_HOOK` as a repository secret) and the Vercel deploy hook are configured.

## Data

- Neon `dev` branch: the holdings tables (fixed_deposits, recurring_deposits, stocks, bonds, mutual_funds) were emptied on 2026-10-25 at the user's request; master/market tables (`mf_schemes`, `mf_nav_latest`, `mf_nav_history`) were kept. The user may enter real holdings there again, so never delete or modify rows you didn't create.

## Known gaps / small follow-ups

- Holdings details page (eye icon) not built yet.
- Forms don't map API 422 `detail` field errors onto inputs (forms validate first, so rarely visible).
- `notify.deleting()` in `web/lib/notify.ts` is unused.
- Generic HTTP error wording ("Request failed") and the routing 404 description were not specified by the user — confirm if they matter.
- `docs/PLAN.md` describes the original plan; `docs/SPEC.md` is current.

## Deferred (not started)

- Live prices for stocks and bonds (current value = invested until then). MF uses the latest AMFI NAV (daily, not live).
- Pruning of unheld schemes' NAV history (see SPEC §1).
- SIP support for MF; transaction history (each holding is one record).
- Full automated test suite (pytest exists in `api/tests`, per-bug tests only), multi-user auth.
- Matured holdings view (pinned for later): matured items are currently listed in grids but excluded from totals.
- Duplicate-holding warnings.

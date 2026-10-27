# STATUS — handoff notes (last updated 2026-10-27)

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
- MF master data from AMFI (mf_schemes, renamed mf_master in migration 0007, + mf_nav_latest; daily cron; scheme picker in MF form).
- Historical NAV lookup (mf_nav_history via mfapi.in, cached) and Average NAV auto-fill in the MF form.
- MF valuation at the latest AMFI NAV (units × NAV for scheme-linked holdings; `nav`/`nav_date` in API items) (SPEC §3).
- After saving an asset, the add form opens that type's portfolio tab (`/portfolio/{type}`).
- MF grid "NAV" column (latest NAV, "as of" date).
- Securities masters for stocks/ETFs (`stock_master`) and bonds (`bond_master`), migration 0006, from NSE/BSE files with a daily cron; stock and bond form pickers with the linked `master_id` (SPEC §1, §4, §5). MF master table renamed `mf_schemes` → `mf_master` (migration 0007).

- Bond master enrichment (committed, not pushed: `49eeb0c`, `79f548f`, `c14bd87`): `bond_master` merged by ISIN from seed files (SGB tranches, tax-free bonds), NSDL India Bond Info list (committed CSV, refreshed manually via `app.jobs.nsdl_convert`), NSE DEBT, NSE ratings and SGB JSON, and bhavcopy GB. New columns: issue date/price, rating + agency, coupon type, interest frequency, issue size, ownership, issue mode, perpetual, NSDL status (migrations 0008, 0009). Social Stock Exchange instruments excluded. SPEC §1 has the details and the refresh procedure.
- Pending, uncommitted: web bond picker shows ratings (`web/components/forms/bond-form.tsx`, `web/lib/types.ts`).

Verified in the browser: add (FD, stock), edit (stock), delete, dashboard numbers, date picker + year dropdown, comma grouping/caret, payout form relabel, API-sourced toasts.
Verified only via API/curl or build: RD/bond/MF save through the UI, per-field validation messages in the forms, edit dialog date picker layering, 500 handler.

## Deployment state

- GitHub: https://github.com/Psyphon361/wealth-track (`origin`, branch `main`). Check `git log origin/main..main` for unpushed commits. As of 2026-10-27, unpushed: `49eeb0c`, `79f548f`, `c14bd87` (bond master enrichment; migrations 0008 and 0009 run on prod via the GitHub Action when pushed). Push only with the user's OK.
- Vercel: user created two projects (root `api/` and root `web/`). Web is live at https://wealth-track-nu.vercel.app — login gate works (unauthenticated `/api/dashboard` → 401, `/` → redirect to /login).
- Production (as of 2026-10-25): migrations ran via the GitHub Action; the production DB is at `0005` (it had been at `0002`, so `0003` is now applied too). `CRON_SECRET` is set. The first AMFI import succeeded (14412 schemes, 8821 active) and the daily cron (22:00 IST) is live. The earlier 404 on `/api/dashboard` after login was fixed. GitHub secrets (`PROD_DATABASE_URL` as a `production` environment secret, `VERCEL_API_DEPLOY_HOOK` as a repository secret) and the Vercel deploy hook are configured.

## Data

- Neon `dev` branch (2026-10-27): `bond_master` 34,284 rows; active corporate 29,325, government 4,531, sgb 44 (67 incl. matured), tax_free 353; 8,750 with a rating. Migration head 0009.
- Neon `dev` branch: the holdings tables (fixed_deposits, recurring_deposits, stocks, bonds, mutual_funds) were emptied on 2026-10-25 at the user's request; master/market tables (`mf_master`, `mf_nav_latest`, `mf_nav_history`, `stock_master`, `bond_master`) were kept. The user may enter real holdings there again, so never delete or modify rows you didn't create.

## Known gaps / small follow-ups

- Holdings details page (eye icon) not built yet.
- Forms don't map API 422 `detail` field errors onto inputs (forms validate first, so rarely visible).
- `notify.deleting()` in `web/lib/notify.ts` is unused.
- Generic HTTP error wording ("Request failed") and the routing 404 description were not specified by the user — confirm if they matter.
- 54EC bonds are not covered in `bond_master` (no cited source). Unlisted G-secs and SDLs are not covered. BSE-only bonds appear only if NSDL lists them.
- The NSDL list is refreshed by hand (monthly suggested). Until the next refresh, new issues are missing from the bond list.
- `tax_free` in `bond_master` depends on the seed file (106 bonds) and the NSDL "Taxfree" flag; `stock_master` has no tax_free detection.
- Bond rating in the picker is pending (uncommitted web change).
- Some NSE ETF names in `stock_master` are raw codes (e.g. "NIPINDETFNIFTYBEES").
- `docs/PLAN.md` describes the original plan; `docs/SPEC.md` is current.

## Deferred (not started)

- Live prices for stocks and bonds (current value = invested until then; price source decision pending). MF uses the latest AMFI NAV (daily, not live).
- Pruning of unheld schemes' NAV history (see SPEC §1).
- SIP support for MF; transaction history (each holding is one record).
- Full automated test suite (pytest exists in `api/tests`, per-bug tests only), multi-user auth.
- Matured holdings view (pinned for later)
- Matured bonds list from NSDL (optional source; not built).: matured items are currently listed in grids but excluded from totals.
- Duplicate-holding warnings.

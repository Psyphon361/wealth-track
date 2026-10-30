# STATUS — handoff notes (last updated 2026-10-30)

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
- Bond amounts (committed, not pushed; migration 0013): `bonds.invested_amount` (total, NOT NULL, backfilled quantity × purchase_price) is the invested value. Face value is no longer a form input (optional in the API, saved from the bond master on pick). The 50–150% of face value price rule is removed from API and form; new rule: total must equal quantity × price (`invested_amount`, tolerance quantity × 0.005 + 0.01). The bond form takes any two of quantity, price and total and calculates the third (`web/lib/bond-amounts.ts`, vitest in `web/lib/bond-amounts.test.ts`, `npm test`). Picking a bond fills maturity always and purchase date only when empty. SPEC §1, §2, §3, §5.
- UI (committed): FD tenure by duration or maturity date (toggle; SPEC §5), toasts top right with no "Saving…" toast, grids left-aligned, figures in Geist sans with tabular-nums.
- FD/RD issuer master (uncommitted and not pushed at time of writing; migration 0011): `fd_issuer_master` from the Razorpay IFSC bank list (categories, DICGC insured flag matched from the DICGC xlsx), short names and 17 mergers from a seed, 16 NBFCs and 11 HFCs from a cited seed, India Post. FD/RD forms have a bank/issuer picker (`issuer_id`; server snapshots `bank`); weekly cron `/api/cron/issuers`. Dev import (2026-10-28): 1,379 issuers: urban_coop 852, district_coop 319, regional_rural 53, state_coop 31, public_sector 28 (incl. merged), foreign 27, private 22, nbfc 16, small_finance 11, hfc 11, payments 6, local_area 2, post_office 1; DICGC matched 852. API tests: 272 passing. SPEC §1, §2, §4, §5.
- Auth step 1 (email and password sign-in, invite-only sign-up, one owner per holding; commits `ca3b832`, `a331552`; web auth W1 and these docs are uncommitted at time of writing). Users, refresh tokens and login attempts; migration `0010` (holdings `user_id`); every holdings route is scoped to the signed-in user; master routes need sign-in. Web sign-in and sign-up pages (password fields with a show/hide eye toggle), account menu in the top bar (email avatar, Log out), httpOnly cookies `wt_access` and `wt_refresh`, token refresh in the route handler. The old `APP_PASSWORD` gate is gone from the code. SPEC §7. API tests: 243 passing.
- Stock prices (built, not pushed; migration `0014` adds `stock_price_latest` and `app_state`): stock current value = quantity × latest price. Prices come from Yahoo Finance (NSE `.NS`, else BSE `.BO`), refreshed on reads of `/api/holdings/stock`, `/api/portfolio` and `/api/dashboard` when stale (every 15 min during market hours, once after the close), with a 3 s budget, 15 min backoff per failed stock and a 15 min Yahoo pause on HTTP 429. The securities import stores the bhavcopy close as backup. Stocks grid has a Price column with day change % and a "Last updated" note. Bonds have no market price (YTM accrual); MF uses the latest AMFI NAV. Open: production check whether Yahoo accepts requests from Vercel. SPEC §3, §5.
- Auth step 2: Sign in with Google (commits `45fd893` API, `3c17ac3` web, not pushed; migration `0012` adds `users.google_sub`). "Continue with Google" on /login and /signup; state and PKCE in the httpOnly cookie `wt_oauth`; the API verifies the ID token against Google's JWKS; signs in by Google id, links an existing account with the same verified email, or creates an allowlisted account without a password. Google sign-ins don't count toward the password rate limit. SPEC §7 ("Sign in with Google"), setup in DEPLOY §5b. API tests: 299 passing. Not yet tested with a real Google client (the user creates it).

Verified in the browser: add (FD, stock), edit (stock), delete, dashboard numbers, date picker + year dropdown, comma grouping/caret, payout form relabel, API-sourced toasts.
Verified only via API/curl or build: RD/bond/MF save through the UI, per-field validation messages in the forms, edit dialog date picker layering, 500 handler.

## Deployment state

- GitHub: https://github.com/Psyphon361/wealth-track (`origin`, branch `main`). Check `git log origin/main..main` for unpushed commits. As of 2026-10-27, unpushed: `49eeb0c`, `79f548f`, `c14bd87` (bond master enrichment; migrations 0008 and 0009 run on prod via the GitHub Action when pushed). Push only with the user's OK.
- Vercel: user created two projects (root `api/` and root `web/`). Web is live at https://wealth-track-nu.vercel.app — login gate works (unauthenticated `/api/dashboard` → 401, `/` → redirect to /login).
- Production (as of 2026-10-25): migrations ran via the GitHub Action; the production DB is at `0005` (it had been at `0002`, so `0003` is now applied too). `CRON_SECRET` is set. The first AMFI import succeeded (14412 schemes, 8821 active) and the daily cron (22:00 IST) is live. The earlier 404 on `/api/dashboard` after login was fixed. GitHub secrets (`PROD_DATABASE_URL` as a `production` environment secret, `VERCEL_API_DEPLOY_HOOK` as a repository secret) and the Vercel deploy hook are configured.
- Auth rollout pending: the production database is not at `0010` yet, and the web project still has `APP_PASSWORD` and `SESSION_SECRET`. Steps (secrets, push, `set-password`, login, remove the old variables) are in `docs/DEPLOY.md` → "Auth rollout (one-time)".

## Data

- Neon `dev` branch (2026-10-27): `bond_master` 34,284 rows; active corporate 29,325, government 4,531, sgb 44 (67 incl. matured), tax_free 353; 8,750 with a rating. `fd_issuer_master` 1,379 rows (import 2026-10-28). Migration head 0014 (stock_price_latest + app_state; 0013 bond invested_amount; 0012 Google sign-in; 0011 FD/RD issuer master; 0010 is auth; sign in with an account created by `app.jobs.users create`).
- Neon `dev` branch: the holdings tables (fixed_deposits, recurring_deposits, stocks, bonds, mutual_funds) were emptied on 2026-10-25 at the user's request; master/market tables (`mf_master`, `mf_nav_latest`, `mf_nav_history`, `stock_master`, `bond_master`) were kept. The user may enter real holdings there again, so never delete or modify rows you didn't create.

## Known gaps / small follow-ups

- FD/RD issuers: Unity Small Finance Bank is not listed (enter it manually); Razorpay RRB names are pre-amalgamation; NBFC/HFC `reg_no` is empty (SPEC §1).
- Holdings details page (eye icon) not built yet.
- Forms don't map API 422 `detail` field errors onto inputs (forms validate first, so rarely visible).
- `notify.deleting()` in `web/lib/notify.ts` is unused.
- Generic HTTP error wording ("Request failed") and the routing 404 description were not specified by the user — confirm if they matter.
- 54EC bonds are not covered in `bond_master` (no cited source). Unlisted G-secs and SDLs are not covered. BSE-only bonds appear only if NSDL lists them.
- The NSDL list is refreshed by hand (monthly suggested). Until the next refresh, new issues are missing from the bond list.
- `tax_free` in `bond_master` depends on the seed file (106 bonds) and the NSDL "Taxfree" flag; `stock_master` has no tax_free detection.
- Bond rating in the picker is pending (uncommitted web change).
- Session errors: when the session is invalid, pages show "Not authorised" with Retry instead of redirecting to `/login` (the proxy only checks the cookie's presence).
- Some NSE ETF names in `stock_master` are raw codes (e.g. "NIPINDETFNIFTYBEES").
- `docs/PLAN.md` describes the original plan; `docs/SPEC.md` is current.

## Next (auth)

- Auth step 2 is built. Next: the user creates the Google OAuth client (DEPLOY §5b) and tests the real flow; fix whatever it shows.
- Auth step 3: password reset and email verification (needs an email provider; not chosen yet).

## Deferred (not started)

- Pruning of unheld schemes' NAV history (see SPEC §1).
- SIP support for MF; transaction history (each holding is one record).
- Full automated test suite (pytest exists in `api/tests`, per-bug tests only).
- Matured holdings view (pinned for later)
- Matured bonds list from NSDL (optional source; not built).: matured items are currently listed in grids but excluded from totals.
- Duplicate-holding warnings.

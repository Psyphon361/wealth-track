# HANDOFF — session resume notes (2026-10-28)

Read after `AGENTS.md`, `docs/STATUS.md` and `docs/SPEC.md`. This file covers what those don't: how the last session worked, what it learned the hard way, and what's next. Verify against the code before acting; update this file when you finish a chunk of work.

## Where things stand
- `origin/main` is at `779595d`. Three local commits are unpushed: `49eeb0c`, `79f548f`, `c14bd87` (bond master enrichment). Push only when the user says so. The web bond picker rating change is uncommitted (`web/components/forms/bond-form.tsx`, `web/lib/types.ts`); review and commit it separately.
- Dev DB migration head is `0010` (auth). Prod is still `0007` until the push runs the GitHub Action. Production (Vercel web + api, Neon `production` branch) is on migration `0007`. Prod masters are populated by the 2026-10-26 securities import (`GET /api/cron/securities` on Vercel, all sources fetched with no errors): `stock_master` 5,765 rows (equity 2,629, etf 355, NSE bhavcopy SME 467, BSE 5,013), `bond_master` 6,205 (debt 6,162, bhavcopy SGB 43); bhavcopy and BSE file date 2026-10-23. `CRON_SECRET` set; AMFI master loaded (14,412 schemes / 8,821 active). Daily crons: securities 14:00 UTC (19:30 IST), AMFI 16:30 UTC (22:00 IST).
- Migration head was `0007` at the start of the 2026-10-26 session (now `0009`, see above). Neon `dev` branch: the master tables are populated: `stock_master` 5,765 rows (5,384 stock + 381 etf), `bond_master` 34,284 (after the 2026-10-27 enrichment), `mf_master` 14,412. All 5 holdings tables were emptied on 2026-10-25 at the user's request (backup JSON was in that session's scratchpad, temporary). Master/market tables kept. The user may enter real holdings again — rule 5 in AGENTS.md still applies.
- API tests: `cd api && .venv/bin/python -m pytest -q` (243 passing). Add a test with every bug fix (user decision: no full suite).

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
7. Auth step 2: Google sign-in. Auth step 3: password reset and email verification (needs an email provider; ask the user which one).

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

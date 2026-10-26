# HANDOFF — session resume notes (2026-10-26)

Read after `AGENTS.md`, `docs/STATUS.md` and `docs/SPEC.md`. This file covers what those don't: how the last session worked, what it learned the hard way, and what's next. Verify against the code before acting; update this file when you finish a chunk of work.

## Where things stand
- `main` is ahead of `origin/main` by unpushed commits (incl. `a1a7b93` MF valuation at latest NAV, `148d2de` post-save redirect to the type tab, `d749f22` MF NAV column, `1732d66` securities master API, `7214d7d` stock/bond master search + cron + holdings link, `ce1beeb` stock and bond pickers); push only when the user says so. Production (Vercel web + api, Neon `production` branch) is on migration `0005`, `CRON_SECRET` set, AMFI master loaded (14,412 schemes / 8,821 active), daily cron 22:00 IST live. Pushing the `api/` commits makes the GitHub Action run `alembic upgrade head` on prod, so `0006` (securities) goes to prod with the push.
- Migration head is `0006` (dev DB). Neon `dev` branch: the securities master is populated (~11,970 rows: 5,384 stock, 381 ETF, 6,205 bond). All 5 holdings tables were emptied on 2026-10-25 at the user's request (backup JSON was in that session's scratchpad, temporary). Master/market tables kept. The user may enter real holdings again — rule 5 in AGENTS.md still applies.
- API tests: `cd api && .venv/bin/python -m pytest -q` (112 passing). Add a test with every bug fix (user decision: no full suite).

## Built this session (committed, unpushed)
- Securities master (`1732d66`, `7214d7d`, `ce1beeb`): `securities` table (migration 0006) from NSE EQUITY_L, ETF list, DEBT (required) plus NSE/BSE UDiFF bhavcopy (optional, walks back 7 days), merged by ISIN; `/api/master/stock`, `/api/master/bond`, `/api/master/security/{id}`; `/api/cron/securities` (Vercel 19:30 IST) and CLI `python -m app.jobs.securities_import` (locally needs `SSL_CERT_FILE`). Stock/bond payloads take `security_id`; the server snapshots name/symbol (stock) or name/ISIN (bond). Web: generic `components/forms/master-picker.tsx` (MF scheme picker is a thin wrapper), stock and bond pickers, linked security in the edit dialog. Known data gaps are in STATUS.
- MF valuation at latest AMFI NAV: current = units × `mf_nav_latest` NAV for scheme-linked holdings (stale NAV still used); manual/no-NAV stay at invested. `/api/portfolio` and `/api/holdings/mf` MF items carry `nav` and `nav_date`. One extra query over held schemes, run concurrently.
- After saving the add form → `/portfolio/{type}`.
- MF grid "NAV" column after Avg NAV (visible by default, not sortable).

## Built in the last session (all shipped)
- `/add` gallery (`web/lib/asset-catalog.ts`) → `/add/[type]` forms; header breadcrumb; global "Add asset" menu in the top bar (shortcut `N`), in-page "Add FD/RD/…" as secondary.
- Inset app frame (sidebar `variant="inset"`, darker frame, rounded content panel).
- Portfolio: `/portfolio` redirects to first held type; `/portfolio/[type]` with Groww-style fixed-width tabs (sliding underline, content fade), summary strip ("N active · M matured"), per-type server-side grids (`GET /api/holdings/{type}`): search, faceted + range filters, sorting, fixed 10 rows/page, column visibility per type in localStorage, eye (disabled, details page TBD) + ⋯ Edit/Delete.
- Matured holdings are closed: excluded from all totals/counts, listed in grids; payout FDs labelled ("interest paid", "over tenure", principal-only tooltip).
- MF master data: `mf_schemes` (static), `mf_nav_latest`, `mf_nav_history` (+ `_sync`), AMFI import (CLI + cron), scheme picker in the MF form, NAV auto-fill by purchase date (mfapi.in, cached).
- CI: `.github/workflows/api-deploy.yml` — push to `main` touching `api/` → `alembic upgrade head` on prod (env secret `PROD_DATABASE_URL` in GitHub env `production`) → Vercel deploy hook (`VERCEL_API_DEPLOY_HOOK`). Vercel git auto-deploy for api `main` is off (`api/vercel.json`). Web still auto-deploys on push.
- `npm run clean` (root) clears `web/.next`, tsbuildinfo, Python caches.

## Next candidates (ask the user which first)
1. Holding details page at `/portfolio/{type}/{id}` (flip `DETAILS_ENABLED` in `components/portfolio/grid/row-actions.tsx`).
2. Polish SGB names/maturity and exclude SSE (series SE) instruments from the securities master.
3. Verify `/api/cron/securities` from Vercel after push (NSE/BSE may block US IPs; fallback: run the CLI locally).
4. Matured holdings view (pinned for later).
5. Prune NAV history of unheld schemes (daily cron, 7-day grace on `fetched_at`) — deferred by user (SPEC §1).
6. Integrations decisions still open with the user: NSE EOD files (grey-area ToS), CAS upload vs broker API, paid data or free only, price history depth, Account Aggregator.

## How the user works (and how the last session ran)
- Orchestrator + builders (see `CLAUDE.md` and `~/.claude/CLAUDE.md`): main session plans, briefs, reviews, verifies in the browser, commits; builders (Sonnet, effort medium) edit; Haiku for docs/chores; max 3 builders in parallel; check usage before dispatching.
- Show a plan before non-trivial builds; the user often answers with short directives — ask with clear options when a choice is genuinely theirs.
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

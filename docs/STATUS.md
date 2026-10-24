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
- Deployment prep: Vercel-ready API (`api/vercel.json`, region iad1, API key), password gate + same-origin proxy in web, `docs/DEPLOY.md`.

Verified in the browser: add (FD, stock), edit (stock), delete, dashboard numbers, date picker + year dropdown, comma grouping/caret, payout form relabel, API-sourced toasts.
Verified only via API/curl or build: RD/bond/MF save through the UI, per-field validation messages in the forms, edit dialog date picker layering, 500 handler.

## Deployment state

- GitHub: https://github.com/Psyphon361/wealth-track (`origin`, branch `main`). Check `git log origin/main..main` for unpushed commits.
- Vercel: user created two projects (root `api/` and root `web/`). Web is live at https://wealth-track-nu.vercel.app — login gate works (unauthenticated `/api/dashboard` → 401, `/` → redirect to /login).
- **OPEN BUG (prod)**: after login, `GET /api/dashboard` on the web app returns **404**. Since the proxy forwarded it, the upstream (`API_URL`) answered 404. Most likely `API_URL` in the web project is wrong (ends with `/api`, points to a deployment-specific/old URL, or the API project failed to deploy). Next step: get the API project's production URL from the user, `curl <api>/api/health` (expect ok) and `<api>/api/dashboard` (expect 401 without key), then fix `API_URL` (no `/api`, no trailing slash) and redeploy web.
- **Production DB**: Neon `production` branch. Migrations must be at head `0003` — ask the user to run `cd api && DATABASE_URL='<prod direct url>' .venv/bin/alembic upgrade head` and confirm `alembic current` = `0003 (head)`. Not confirmed yet.

## Data

- Neon `dev` branch holds the user's REAL holdings (e.g. an "axis" FD and a government bond "Tanish"). Never delete or modify rows you didn't create.

## Known gaps / small follow-ups

- Forms don't map API 422 `detail` field errors onto inputs (forms validate first, so rarely visible).
- `notify.deleting()` in `web/lib/notify.ts` is unused.
- Generic HTTP error wording ("Request failed") and the routing 404 description were not specified by the user — confirm if they matter.
- `docs/PLAN.md` describes the original plan; `docs/SPEC.md` is current.

## Deferred (not started)

- Live prices/NAV for stocks, MF, bonds (current value = invested until then).
- SIP support for MF; transaction history (each holding is one record).
- Automated tests, multi-user auth.
- Duplicate-holding warnings.

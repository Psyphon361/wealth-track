# Wealth Tracker — Prototype v1 Build Plan

Barebones prototype: build fast, fail fast. No automated testing in v1; each task is verified by build/run/curl/click-through smoke checks.

## Stack
- Monorepo: `api/` (FastAPI) + `web/` (Next.js).
- API: FastAPI, SQLAlchemy 2, Alembic, psycopg 3, Pydantic v2; Python venv + `requirements.txt`.
- Web: Next.js (App Router, TypeScript), Tailwind, shadcn/ui, react-hook-form + zod; npm.
- DB: Neon Postgres (`dev` branch for development, `main` for deployment). Pooled connection string in `api/.env` as `DATABASE_URL`.
- Single user, no auth locally. INR only. No live prices.

## Data model
One table per asset type. Every table also has `id`, `notes` (optional), `created_at`, `updated_at`.
Money: Numeric(14,2). Rates (% p.a.): Numeric(6,3). MF units: Numeric(14,3). `?` = optional.

### fixed_deposits
bank, label?, principal, rate, start_date, tenure_years, tenure_months, tenure_days, compounding (monthly | quarterly | half_yearly | yearly | simple; default quarterly), payout_type (cumulative | payout).

### recurring_deposits
bank, label?, monthly_instalment, rate, start_date, tenure_years, tenure_months, tenure_days, compounding (same options; default quarterly).

### stocks
name, symbol?, exchange (NSE | BSE; default NSE), broker?, quantity (int), avg_buy_price, buy_date.

### bonds
name, isin?, issuer, bond_type (government | corporate | tax_free | sgb | other), platform?, quantity (int), purchase_price (per unit), purchase_date, ytm, maturity_date.

### mutual_funds
scheme_name, platform?, category (equity | debt | hybrid | index | elss | liquid | other), units, avg_nav, purchase_date.

Validation: tenure total > 0; amounts, rates, quantities > 0.

## API contract (prefix `/api`, snake_case JSON)
- CRUD per type, `{type}` ∈ `fd | rd | stock | bond | mf`:
  - `GET /assets/{type}`, `POST /assets/{type}`
  - `GET /assets/{type}/{id}`, `PUT /assets/{type}/{id}`, `DELETE /assets/{type}/{id}`
- `GET /portfolio` → `{ groups: [{ type, label, items: [...], totals: { invested, current_value, gain, gain_pct } }] }`. Each item = stored fields + computed `invested`, `current_value`, `gain`, `gain_pct`, and where relevant `maturity_date`, `status` (active | matured).
- `GET /dashboard` → `{ total_invested, total_current, total_gain, gain_pct, by_type: [{ type, label, count, invested, current, allocation_pct }] }`.
- `GET /health` → `{ status: "ok" }`.

## Calculations (server side)
- FD: maturity_date = start_date + tenure (years, months, days). status = matured if today ≥ maturity_date else active. invested = principal. current_value = principal compounded at `rate` with the chosen frequency up to min(today, maturity_date); simple → principal × (1 + r × t). Payout-type FDs use the same formula.
- RD: maturity_date and status as FD. Instalments on the same day each month from start_date while date < maturity_date and date ≤ today (assumed paid on time). invested = count × monthly_instalment. current_value = sum of each instalment compounded quarterly (or chosen frequency) for its elapsed time up to min(today, maturity_date).
- Bond: invested = quantity × purchase_price. current_value = invested × (1 + ytm)^(years from purchase_date to min(today, maturity_date)). status from maturity_date.
- Stock: invested = quantity × avg_buy_price; current_value = invested (until a price API exists).
- MF: invested = units × avg_nav; current_value = invested (until a NAV API exists).
- Matured items stay in totals at their maturity value, labelled Matured.

## UI
- Nav: Dashboard, Portfolio.
- Dashboard: total cards (invested, current value, gain ₹/%), table by asset type (count, invested, current, allocation %). No chart in v1.
- Portfolio: sections grouped by asset type, table per section with computed values; edit (dialog reusing the input form) and delete (with confirm); "Add asset" flow: pick type → form.
- Forms: one per asset type, shared Years/Months/Days tenure picker (FD, RD).

## Tasks

| # | Task | Files | Acceptance | Depends on |
|---|---|---|---|---|
| 0 | Repo setup: `git init`, move `claude/` → `.claude/`, register hook in `.claude/settings.json`, `.gitignore`, README stub, this plan at `docs/PLAN.md` | root, `.claude/`, `docs/` | first commit clean; hook registered | — |
| 1 | API scaffold: app, settings from env, DB session, CORS (`localhost:3000`), `/api/health` | `api/` | `uvicorn` starts; `curl /api/health` ok | 0 |
| 2 | Models + first Alembic migration (5 tables) | `api/app/models`, `api/alembic` | `alembic upgrade head` succeeds on Neon dev | 1, Neon URL |
| 3 | Pydantic schemas + CRUD routers (5 types) | `api/app/schemas`, `api/app/routers` | curl create/list/update/delete per type; bad input → 422 | 2 |
| 4 | Calculation service + `/portfolio`, `/dashboard` | `api/app/services`, routers | values match hand-worked examples for one FD, RD, bond | 3 |
| 5 | Web scaffold: Next.js + shadcn init, nav layout (Dashboard, Portfolio), typed API client (`NEXT_PUBLIC_API_URL`) | `web/` | `npm run build` passes | 0 |
| 6 | 5 input forms + shared tenure picker + "Add asset" flow | `web/components/forms`, add page | each form saves via API; validation errors show | 3, 5 |
| 7 | Portfolio tab: grouped sections, computed values, edit dialog (reuse forms), delete w/ confirm | `web/app/portfolio` | edit/delete works for each type; totals update | 4, 6 |
| 8 | Dashboard: total cards + by-type table | `web/app/page.tsx`, `web/components/dashboard` | numbers match `/api/dashboard` | 4, 5 |
| 9 | Deploy (later): password gate, Vercel + Render + Neon main | — | separate plan | 1–8 |

Order: 0 → (1 ∥ 5) → 2 → 3 → 4 → (6 ∥ 8) → 7.

## Deployment notes (Task 9, later)
- Free options: Vercel Hobby (web), Render free / Koyeb / Cloud Run (API), Neon free (DB). Re-check free-tier terms at deploy time.
- Must add a password gate before going public (no auth otherwise exposes financial data).
- Cold starts (Render sleep, Neon idle) → loading states in UI.
- CORS for the Vercel domain; env vars per platform; run Alembic migrations against Neon main; use Neon pooled connection string.

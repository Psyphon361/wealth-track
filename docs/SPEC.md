# SPEC — current behaviour (source of truth for v1)

Supersedes the data-model and validation parts of `docs/PLAN.md` (kept for history). Code locations: models `api/app/models/`, validation `api/app/schemas/assets.py` + `web/components/forms/schema.ts`, maths `api/app/services/valuation.py`.

## 1. Asset types and fields

Every table also has `id`, `notes` (optional, ≤ 1000 chars), `created_at`, `updated_at`. `?` = optional. Money = ₹.

| Type (`{type}` slug) | Table | Fields |
|---|---|---|
| Fixed Deposit (`fd`) | `fixed_deposits` | bank, label?, principal, rate (% p.a.), start_date, tenure_years, tenure_months, tenure_days, compounding (`monthly`\|`quarterly`\|`half_yearly`\|`yearly`\|`simple`, default quarterly), payout_type (`cumulative`\|`payout`) |
| Recurring Deposit (`rd`) | `recurring_deposits` | bank, label?, monthly_instalment, rate, start_date, tenure_years, tenure_months, tenure_days, compounding (default quarterly) |
| Stock (`stock`) | `stocks` | name, symbol?, exchange (`NSE`\|`BSE`, default NSE), broker?, quantity (int), avg_buy_price, buy_date |
| Bond (`bond`) | `bonds` | name, isin?, issuer, bond_type (`government`\|`corporate`\|`tax_free`\|`sgb`\|`other`), platform?, quantity (int), face_value (per unit; nullable in DB for old rows, required on input), purchase_price (per unit), purchase_date, ytm (% p.a.), maturity_date |
| Mutual Fund (`mf`) | `mutual_funds` | scheme_name, platform?, category (`equity`\|`debt`\|`hybrid`\|`index`\|`elss`\|`liquid`\|`other`), units (3 dp), avg_nav (4 dp), purchase_date |

Column precision: money Numeric(14,2), rate/ytm Numeric(6,3) (input limited to 2 dp), units Numeric(14,3), avg_nav Numeric(14,4). Enums are VARCHAR + CHECK (not native PG enums).

Removed by user decision: FD maturity amount & status inputs, stock current price (future API), MF AMC/folio/plan/option, SIP support, bond coupon rate/frequency (YTM used instead).

## 2. Validation rules (API and forms, identical wording)

Base: required text non-empty ("Required"); numbers must parse ("Enter a valid number"); amounts/rates/quantities > 0 ("Must be greater than 0"); quantity whole ("Must be a whole number").

| # | Rule | Message |
|---|---|---|
| 1 | FD/RD rate: > 0 and ≤ 15, max 2 dp | Interest rate must be between 0 and 15% |
| 2 | Bond ytm: > 0 and ≤ 30, max 2 dp | YTM must be between 0 and 30% |
| 3 | Decimal places: money 2, rates 2, MF units 3, MF avg_nav 4 | Up to N decimal places allowed |
| 5 | Every ₹ field ≤ 1,000,000,000 | Must be at most ₹100 crore |
| 6 | Stock/bond quantity, MF units ≤ 10,000,000 | Must be at most 1 crore |
| 7 | start_date / buy_date / purchase_date ≤ today + 30 days | Date can be at most 30 days in the future |
| 8 | Every date ≥ 1990-01-01 | Date must be on or after 1 Jan 1990 |
| 9 | FD: start + 7 days ≤ maturity ≤ start + 10 years | FD tenure must be between 7 days and 10 years |
| 10 | RD: start + 6 months ≤ maturity ≤ start + 10 years | RD tenure must be between 6 months and 10 years |
| 11 | Tenure parts: years 0–10, months 0–11, days 0–30; total > 0 | Years/Months/Days must be between 0 and N; Tenure must be greater than zero |
| 12 | Bond maturity > purchase, and ≤ purchase + 50 years | Maturity date must be after the purchase date / Maturity must be within 50 years of purchase |
| 13 | Bond purchase_price within 50%–150% of face_value | Purchase price should be between 50% and 150% of face value |
| 14 | ISIN (optional): uppercased, `^[A-Z]{2}[A-Z0-9]{9}[0-9]$` | ISIN must be 12 characters, e.g. INE002A01018 |
| 15 | Symbol (optional): uppercased, `^[A-Z0-9&-]{1,20}$` | Symbol: letters, digits, & or -, up to 20 characters |
| 16 | Text ≤ 200 chars (names, bank, label, issuer, broker, platform, scheme); notes ≤ 1000 | Must be at most N characters |
| P | Payout FD cannot use `simple` | Choose a payout frequency |

No minimum amounts beyond > 0 (user decision). Cross-field errors are attached to a field: tenure → `tenure_years`, payout frequency → `compounding`, price range → `purchase_price`, maturity rules → `maturity_date`. Read models accept existing rows even if they'd fail new create-time rules.

## 3. Valuation (server side, `valuation.py`)

Year fraction = days / 365. Rates are percent. Periods/yr: monthly 12, quarterly 4, half_yearly 2, yearly 1.

- **Maturity date** (FD, RD) = start + relativedelta(years, months) + days. **Status** = `matured` if today ≥ maturity else `active` (bond: from maturity_date).
- **FD cumulative**: invested = principal; current = P × (1 + r/n)^(n·t), `simple` → P × (1 + r·t); t from start to min(today, maturity).
- **FD payout** (`payout_type = payout`; `compounding` holds the payout frequency): invested = current = principal; `interest_received` = P × r/n × completed payout periods (period ends every 12/n months after start, ≤ min(today, maturity)); if matured, plus the final partial period up to maturity (total = simple interest over the tenure). gain = interest_received.
- **RD**: instalments on start + k months while date < maturity and ≤ today (assumed paid on time); invested = count × instalment; current = Σ each instalment compounded (same rule) to min(today, maturity).
- **Bond**: invested = quantity × purchase_price; current = invested × (1 + ytm/100)^t, t from purchase to min(today, maturity). face_value is display-only.
- **Stock / MF**: invested = qty × avg_buy_price / units × avg_nav; current = invested (no price API yet).
- gain = current − invested (payout FD: interest_received); gain_pct = gain / invested × 100. Group and dashboard totals SUM item gains (not current − invested). Outputs rounded to 2 dp.

Reference checks: FD 100000 @ 7% quarterly, start 2025-10-24, 1y, on 2026-10-24 → 107185.90. Payout FD 100000 @ 7.2% quarterly 1y → 3600.00 after 2 quarters, 7200.00 at maturity. Bond 10 × 1000, ytm 8, 1 year → 10800.00.

## 4. API (prefix `/api`, snake_case JSON, decimals as numbers)

- `GET /health` → `{"status":"ok"}` (no API key needed).
- `GET|POST /assets/{type}`, `GET|PUT|DELETE /assets/{type}/{id}`; PUT is a full replace.
- `GET /portfolio` → `{groups:[{type,label,items[],totals{invested,current_value,gain,gain_pct}}]}` — always 5 groups in order fd, rd, stock, bond, mf. Items = record fields + `invested, current_value, gain, gain_pct, status`, plus `maturity_date` (fd/rd/bond) and `interest_received` (payout FD).
- `GET /dashboard` → `{total_invested,total_current,total_gain,gain_pct,by_type:[{type,label,count,invested,current,allocation_pct}]}`.
- Auth: if `API_KEY` env is set, every route except `/api/health` and OPTIONS needs header `X-API-Key` (401 otherwise).

### Message contract (toasts render these verbatim)
- POST 201 → record + `message` ("Fixed deposit added" / "Recurring deposit added" / "Stock added" / "Bond added" / "Mutual fund added") + `description` (holding name: FD/RD bank[ · label], stock/bond name, MF scheme_name).
- PUT 200 → record + `message: "Changes saved"` + description.
- DELETE **200** → `{message: "<Type> deleted", description}`.
- Errors always: `{message, description, detail}`. 422 → "Couldn't save — check the highlighted fields" + first field error ("Principal: Must be at most ₹100 crore"), `detail` = list of {loc,msg,type}. 404 → "<Type> not found" / "It may have been deleted already." 401 → "Not authorised" / "Your session may have expired. Log in again." 500 → "Something went wrong on the server" (+ error class only). Other HTTP errors → "Request failed".
- Next.js proxy's own errors use the same shape: 401 "Not logged in", 502 "Couldn't reach the server", 503 "Server not configured", 400 "Bad request".

## 5. Web app

- Pages: `/` Dashboard (KPI cards, holdings-by-type table with allocation bars), `/portfolio` (card per non-empty type, compact tables, edit dialog reusing forms, optimistic delete with confirm, background refresh indicator), `/add?type=fd|rd|stock|bond|mf` (ToggleGroup type picker + form), `/login`.
- Browser calls only same-origin `/api/*`; `app/api/[...path]/route.ts` forwards to `API_URL` with `X-API-Key`.
- Password gate (`proxy.ts` + `lib/session.ts`): enabled when `APP_PASSWORD` set; `SESSION_SECRET` signs a 30-day httpOnly cookie `wt_session`; production with no password fails closed (503). Logout in the sidebar footer. Gate is off in local dev.
- Inputs: money/quantity/units use Indian digit grouping while typing (`components/forms/number-format.ts`); dates via themed DateField (Popover + Calendar, Monday first, month/year custom dropdowns, days outside allowed range disabled); payout FDs relabel Compounding → "Payout frequency" without Simple.
- Toasts (sonner, themed): title = API `message`, description = API `description`.
- Theme: dark only, zinc palette, emerald primary, Geist Sans/Mono, root font-size 110%, sidebar 13.5rem.

## 6. Environment variables

| Where | Var | Notes |
|---|---|---|
| api | `DATABASE_URL` | Neon pooled string (`postgresql://…?sslmode=require`; normalised to psycopg3) |
| api | `API_KEY` | optional locally; required in production |
| api | `CORS_ORIGINS` | default `["http://localhost:3000"]`; not needed in production (proxy) |
| web | `API_URL` | FastAPI origin, no trailing slash, no `/api` (default http://localhost:8000) |
| web | `API_KEY` | same value as api |
| web | `APP_PASSWORD`, `SESSION_SECRET` | production only (`openssl rand -hex 32` for the secret) |

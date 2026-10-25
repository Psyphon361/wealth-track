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
| Mutual Fund (`mf`) | `mutual_funds` | scheme_code? (FK → `mf_schemes.scheme_code`), scheme_name, platform?, category (`equity`\|`debt`\|`hybrid`\|`index`\|`elss`\|`liquid`\|`other`), units (3 dp), avg_nav (4 dp), purchase_date |

Column precision: money Numeric(14,2), rate/ytm Numeric(6,3) (input limited to 2 dp), units Numeric(14,3), avg_nav Numeric(14,4). Enums are VARCHAR + CHECK (not native PG enums).

Removed by user decision: FD maturity amount & status inputs, stock current price (future API), MF AMC/folio/plan/option, SIP support, bond coupon rate/frequency (YTM used instead).

### Master data (MF)

- **`mf_schemes`** (static; daily upsert writes only rows that changed): scheme_code PK, name, amc, amfi_category, category (mapped to the app enum), plan (direct/regular), option (growth/idcw/bonus/other), idcw_frequency, isin_growth_payout, isin_reinvest, is_active, updated_at.
- **`mf_nav_latest`:** scheme_code PK/FK, nav (4 dp), nav_date. One current NAV per scheme.
- **Source:** AMFI `https://portal.amfiindia.com/spages/NAVAll.txt`. A scheme is active if its NAV date is within 30 days of the file's latest date. Rows are never deleted.
- **Category mapping** (AMFI category → app enum):
  - ELSS → elss
  - other Equity → equity
  - Liquid/Overnight/Money Market → liquid
  - other Debt → debt
  - Hybrid → hybrid
  - Index Funds/Other ETFs → index
  - else → other
- **Planned next phase (not built), `mf_nav_history`:** global market data with no user_id. Daily NAVs only for schemes held by at least one holding; backfill from mfapi.in when a scheme is first held, from its purchase date; retention from the earliest purchase date of that scheme, capped at 10 years; prune schemes nobody has held for 90 days.

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
| 17 | MF `scheme_code` (optional) must exist in `mf_schemes` | Select a scheme from the list |
| P | Payout FD cannot use `simple` | Choose a payout frequency |

MF scheme picker: the form requires a scheme in picker mode; "Not listed? Enter manually" allows free text with a null `scheme_code`. When a code is set, the server snapshots `scheme_name` from the master.

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
- **Matured holdings are closed**: they still appear in `items` (status Matured) but are excluded from every total (group totals, dashboard totals/allocation, holdings `summary`) and from `count`. `matured_count` reports how many were excluded.

Reference checks: FD 100000 @ 7% quarterly, start 2025-10-24, 1y, on 2026-10-24 → 107185.90. Payout FD 100000 @ 7.2% quarterly 1y → 3600.00 after 2 quarters, 7200.00 at maturity. Bond 10 × 1000, ytm 8, 1 year → 10800.00.

## 4. API (prefix `/api`, snake_case JSON, decimals as numbers)

- `GET /health` → `{"status":"ok"}` (no API key needed).
- `GET /master/mf?q=&limit=20` → active schemes from `mf_schemes` with nav and nav_date. `q` ≥ 2 characters; every token must match; ranked by trigram similarity.
- `GET /master/mf/{scheme_code}` → one scheme (with nav and nav_date); 404 "Scheme not found".
- `GET /cron/amfi` → runs the AMFI import and returns counts. No X-API-Key; requires `Authorization: Bearer $CRON_SECRET`. Vercel Cron runs it daily at `30 16 * * *` UTC (22:00 IST).
- `GET|POST /assets/{type}`, `GET|PUT|DELETE /assets/{type}/{id}`; PUT is a full replace.
- `GET /portfolio` → `{groups:[{type,label,items[],totals{invested,current_value,gain,gain_pct},count,matured_count}]}` (totals and count cover active holdings only) — always 5 groups in order fd, rd, stock, bond, mf. Items = record fields + `invested, current_value, gain, gain_pct, status`, plus `maturity_date` (fd/rd/bond) and `interest_received` (payout FD).
- `GET /dashboard` → `{total_invested,total_current,total_gain,gain_pct,by_type:[{type,label,count,matured_count,invested,current,allocation_pct}]}`.
- `GET /holdings/{fd|rd|stock|bond|mf}` → server-side grid for one asset type. Values all holdings of that type, then filters, sorts and paginates in Python.
  - Common params:
    - `q` (search)
    - `sort` (default current_value)
    - `dir` (asc|desc, default desc)
    - `page` (clamped to the last page)
    - Page size is fixed at 10; there is no `page_size` param.
  - Filters per type:
    - fd: `bank*`, `payout_type`, `compounding`, `status`, `rate_min`/`rate_max`, `maturity_from`/`maturity_to`
    - rd: `bank*`, `status`, `rate_min`/`rate_max`, `maturity_from`/`maturity_to`
    - stock: `exchange`, `broker*`
    - bond: `bond_type`, `issuer*`, `platform*`, `status`, `ytm_min`/`ytm_max`, `maturity_from`/`maturity_to`
    - mf: `category`, `platform*`
    - (`*` = free-text values whose options come from the data.)
  - Response: `{items (record + computed values), total, page, page_size: 10, page_count, summary{count, matured_count, invested, current_value, gain, gain_pct} for the whole type (unfiltered; active holdings only, count = active count), facets{<filter>: [{value, count}]}}`. Each facet counts rows matching every other filter. Enum facets list all values; text facets list values present for that type.
  - Item: record fields + `invested, current_value, gain, gain_pct, status`, plus `maturity_date` (fd/rd/bond) and `interest_received` (payout FD).
- Auth: if `API_KEY` env is set, every route except `/api/health`, `/api/cron/amfi` (bearer `CRON_SECRET` instead) and OPTIONS needs header `X-API-Key` (401 otherwise).

### Message contract (toasts render these verbatim)
- POST 201 → record + `message` ("Fixed deposit added" / "Recurring deposit added" / "Stock added" / "Bond added" / "Mutual fund added") + `description` (holding name: FD/RD bank[ · label], stock/bond name, MF scheme_name).
- PUT 200 → record + `message: "Changes saved"` + description.
- DELETE **200** → `{message: "<Type> deleted", description}`.
- Errors always: `{message, description, detail}`. 422 → "Couldn't save — check the highlighted fields" + first field error ("Principal: Must be at most ₹100 crore"), `detail` = list of {loc,msg,type}. 422 on `GET /holdings/*` → "Invalid filters" + first error. 404 → "<Type> not found" / "It may have been deleted already." 401 → "Not authorised" / "Your session may have expired. Log in again." 500 → "Something went wrong on the server" (+ error class only). Other HTTP errors → "Request failed".
- Next.js proxy's own errors use the same shape: 401 "Not logged in", 502 "Couldn't reach the server", 503 "Server not configured", 400 "Bad request".

## 5. Web app

- Pages: `/` Dashboard (KPI cards, holdings-by-type table with allocation bars; asset-type rows link to `/portfolio/{type}`).
  - `/portfolio` redirects to the first asset type you hold.
  - `/portfolio/{type}` shows Groww-style fixed-width tabs (FD, RD, Stocks, Bonds, Mutual Funds, with counts) and a sliding underline. The content fades in when the type changes; reduced motion is respected.
  - Each type has a summary strip (count, invested, current, gain) and an "Add FD"/"Add RD"/"Add stocks"/… button linking to `/add/{type}`.
  - Its own grid has type-specific columns and filters. Stocks and MF include Current/Gain/Gain %, which equal invested and 0 until live prices exist.
  - The grid has debounced search, faceted filters, %-range and maturity-date range filters, Reset, and a Columns menu saved per type in localStorage `wt.portfolio.columns.{type}`.
  - Sortable headers; 10 rows per page; no totals row.
  - Row actions: eye (disabled, "Details coming soon"; future `/portfolio/{type}/{id}`) and ⋯ Edit/Delete.
  - State lives in the URL. Breadcrumb reads `Portfolio › {type label}`.
- `/add` (gallery of asset-type tiles grouped Deposits / Market-linked, each with an "N held" count from `/api/dashboard`; registry in `web/lib/asset-catalog.ts`), `/add/{fd|rd|stock|bond|mf}` (form for that type; back link to `/add`; save → `/portfolio`, cancel → `/add`; unknown type → 404; legacy `/add?type=x` redirects to `/add/x`), `/login`.
- Browser calls only same-origin `/api/*`; `app/api/[...path]/route.ts` forwards to `API_URL` with `X-API-Key`.
- Password gate (`proxy.ts` + `lib/session.ts`): enabled when `APP_PASSWORD` set; `SESSION_SECRET` signs a 30-day httpOnly cookie `wt_session`; production with no password fails closed (503). Logout in the sidebar footer. Gate is off in local dev.
- MF form (`components/forms/scheme-picker.tsx`): scheme picker is a server search over `/api/master/mf`, showing AMC · Plan · Option and the latest NAV. Picking sets the name and category (category stays editable). "Not listed? Enter manually" switches to free text.
- Inputs: money/quantity/units use Indian digit grouping while typing (`components/forms/number-format.ts`); dates via themed DateField (Popover + Calendar, Monday first, month/year custom dropdowns, days outside allowed range disabled); payout FDs relabel Compounding → "Payout frequency" without Simple.
- Toasts (sonner, themed): title = API `message`, description = API `description`.
- Theme: dark only, zinc palette, emerald primary, Geist Sans/Mono, root font-size 110%, sidebar 13.5rem.

## 6. Environment variables

| Where | Var | Notes |
|---|---|---|
| api | `DATABASE_URL` | Neon pooled string (`postgresql://…?sslmode=require`; normalised to psycopg3) |
| api | `API_KEY` | optional locally; required in production |
| api | `CRON_SECRET` | production (`openssl rand -hex 32`); bearer token for `/api/cron/amfi` |
| api | `CORS_ORIGINS` | default `["http://localhost:3000"]`; not needed in production (proxy) |
| web | `API_URL` | FastAPI origin, no trailing slash, no `/api` (default http://localhost:8000) |
| web | `API_KEY` | same value as api |
| web | `APP_PASSWORD`, `SESSION_SECRET` | production only (`openssl rand -hex 32` for the secret) |

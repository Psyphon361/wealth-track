# SPEC — current behaviour (source of truth for v1)

Supersedes the data-model and validation parts of `docs/PLAN.md` (kept for history). Code locations: models `api/app/models/`, validation `api/app/schemas/assets.py` + `web/components/forms/schema.ts`, maths `api/app/services/valuation.py`.

## 1. Asset types and fields

Every table also has `id`, `notes` (optional, ≤ 1000 chars), `created_at`, `updated_at`. `?` = optional. Money = ₹.

| Type (`{type}` slug) | Table | Fields |
|---|---|---|
| Fixed Deposit (`fd`) | `fixed_deposits` | bank, issuer_id? (FK → `fd_issuer_master`, ON DELETE SET NULL), label?, principal, rate (% p.a.), start_date, tenure_years, tenure_months, tenure_days, compounding (`monthly`\|`quarterly`\|`half_yearly`\|`yearly`\|`simple`, default quarterly), payout_type (`cumulative`\|`payout`) |
| Recurring Deposit (`rd`) | `recurring_deposits` | bank, issuer_id? (FK → `fd_issuer_master`, ON DELETE SET NULL), label?, monthly_instalment, rate, start_date, tenure_years, tenure_months, tenure_days, compounding (default quarterly) |
| Stock (`stock`) | `stocks` | name, symbol?, exchange (`NSE`\|`BSE`, default NSE), broker?, quantity (int), avg_buy_price, buy_date, master_id? (FK → `stock_master`, ON DELETE SET NULL) |
| Bond (`bond`) | `bonds` | name, isin?, issuer, bond_type (`government`\|`corporate`\|`tax_free`\|`sgb`\|`other`), platform?, quantity (int), face_value? (per unit; nullable; not a form input, saved from the bond master on pick when available), purchase_price (per unit), invested_amount (total invested; NOT NULL; migration 0013, backfilled as quantity × purchase_price), purchase_date, ytm (% p.a.), maturity_date, master_id? (FK → `bond_master`, ON DELETE SET NULL) |
| Mutual Fund (`mf`) | `mutual_funds` | scheme_code? (FK → `mf_master.scheme_code`), scheme_name, platform?, category (`equity`\|`debt`\|`hybrid`\|`index`\|`elss`\|`liquid`\|`other`), units (3 dp), avg_nav (4 dp), purchase_date |

Column precision: money Numeric(14,2), rate/ytm Numeric(6,3) (input limited to 2 dp), units Numeric(14,3), avg_nav Numeric(14,4). Enums are VARCHAR + CHECK (not native PG enums).

Removed by user decision: FD maturity amount & status inputs, stock current price (future API), MF AMC/folio/plan/option, SIP support, bond coupon rate/frequency (YTM used instead).

### Master data (MF)

- **`mf_master`** (static; daily upsert writes only rows that changed; renamed from `mf_schemes` in migration 0007, metadata-only): scheme_code PK, name, amc, amfi_category, category (mapped to the app enum), plan (direct/regular), option (growth/idcw/bonus/other), idcw_frequency, isin_growth_payout, isin_reinvest, is_active, updated_at. Model `MFMaster` (`api/app/models/mf_master.py`).
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
- **`mf_nav_history`** (scheme_code FK, nav_date, nav; PK scheme_code + nav_date) and **`mf_nav_history_sync`** (scheme_code PK, first_date, last_date, fetched_at). Global market data with no user_id.
- **Filled on demand:** the first lookup for a scheme fetches its full history from mfapi.in (`https://api.mfapi.in/mf/{code}`), stores the last 10 years, and records the sync. It refetches at most once per 24 h.
- **Daily cron:** also appends today's NAV for schemes referenced by any holding's `scheme_code`.
- **Not built yet:** pruning of NAV history for schemes nobody holds (proposed: daily cron, 7-day grace on `fetched_at`; deferred by user).

### Master data (stocks/bonds)

One master table per asset class; they are never merged (keeps each table's columns and rules separate).

- **`stock_master`** (static; daily import writes only rows that changed; model `api/app/models/stock_master.py`): id, isin UNIQUE, kind (`stock`\|`etf`), name, nse_symbol, nse_series, bse_code, bse_symbol, bse_group, face_value, is_active, last_seen, updated_at. Trigram index on lower(name). Service `api/app/services/stock_master.py`.
  - Sources: NSE `EQUITY_L.csv` (kind stock), NSE `eq_etfseclist.csv` (kind etf) (both required); NSE UDiFF CM bhavcopy zip (SME series SM/ST → stock) and BSE UDiFF bhavcopy (non-INF ISIN → stock, INF → etf) (optional). BSE government securities (group G) are skipped; NSE DEBT ISINs are dropped here (they belong to `bond_master`).
  - Merge by ISIN: fill order equity/etf, then bhav, then bse; the first source wins.
- **`bond_master`** (static; daily import writes only rows that changed; model `api/app/models/bond_master.py`): id, isin UNIQUE, name, issuer, nse_symbol, nse_series, face_value, coupon_rate, maturity_date, bond_type (NOT NULL), issue_date, issue_price, rating, rating_agency, rating_as_of, coupon_type, interest_frequency (`monthly`\|`quarterly`\|`half_yearly`\|`yearly`\|`on_maturity`\|`irregular`\|`none`), issue_size, issuer_ownership (`psu`\|`non_psu`\|`ildm`), issue_mode (`public`\|`private`\|`rights`\|`bonus`\|`other`), is_perpetual, nsdl_status, sources (internal tags), is_active, last_seen, updated_at. Trigram index on lower(name). Service `api/app/services/bond_master.py` (module docstring lists the sources). Migrations 0008 (issue, rating and sources columns) and 0009 (NSDL columns).
  - Sources, merged by ISIN (tags stored in `sources`): `seed_sgb` (`api/data/sgb_tranches.csv`, 67 SGB tranches with ISIN, dates, coupon, issue price), `seed_tax_free` (`api/data/tax_free_bonds.csv`, 106 tax-free bonds), `nsdl` (`api/data/nsdl_securities.csv`, 29,678 corporate and PSU debt ISINs from the NSDL India Bond Info "List of Securities" export, as_of 2026-10-27), `debt` (NSE `DEBT.csv`, required; 15 columns, ISIN column has no header), `nse_ratings` (NSE liveBonds JSON, credit rating and agency for traded bonds), `nse_sgb` (NSE sovereign-gold-bonds JSON, issue price joined by NSE symbol), `bhav` (NSE UDiFF CM bhavcopy zip, GB series → sovereign gold bonds). Only `debt` is required; every other source is optional, and a failing optional source never aborts the import, never clears stored values and never rewrites source tags.
  - Merge priority per field: seeds > nsdl > debt > nse_ratings/nse_sgb > bhav (a lower source fills only empty fields). Rating prefers `nse_ratings` (fresh daily) over `nsdl`. Name: seeds > debt (it carries the NSE symbol) > nsdl-generated "{Issuer} {coupon}% {NCD|Bond} {Mon YYYY}" ("Perpetual" when perpetual). Tax-free seed names read "{issuer} {coupon}% Tax-free {Mon YYYY}"; government names read e.g. "7.18% GOI 2033", "6.6% Rajasthan SDL 2030", "T-Bill dd Mon yyyy".
  - bond_type: seeds first, then NSDL "Taxfree" → tax_free, then the debt derivation (series GS/TB/SG → government, GB → sgb, tax-free markers in name/issuer/symbol → tax_free), else corporate.
  - Excluded: Social Stock Exchange instruments (symbols ending `-SE`, INS ISINs) are left out entirely (reported as `excluded`).
  - Activity: rows with an NSE symbol that are missing from `DEBT.csv` deactivate at once; rows without one (NSDL-only, seed-only) and GB rows deactivate only after 30 days unseen.
  - **NSDL refresh (manual, monthly suggested):** download the "List of Securities" (Active) xlsx from https://www.indiabondinfo.nsdl.com → Data & Reports → Download Reports → Instrument List Reports (needs a normal browser; the site blocks automation). Run `cd api && .venv/bin/python -m app.jobs.nsdl_convert <xlsx> [--as-of YYYY-MM-DD]` (openpyxl is a dev dependency only), commit the regenerated `api/data/nsdl_securities.csv`, push when the user agrees; the daily cron picks it up. Prod never reads the xlsx.
- **Shared import helpers** (`api/app/services/market_files.py`): download, parse and upsert helpers used by both masters. `fetch_sources` downloads each file once, even when two masters read it (the NSE bhavcopy feeds both). Daily files walk back up to 7 days. BSE requests send a Referer header.
- **Activity:** rows from the required lists deactivate when missing; bhavcopy/BSE-only rows deactivate after 30 days unseen (`last_seen` refreshed at weekly resolution). Rows are never deleted.
- **Holdings link:** stock payloads accept `master_id` (→ `stock_master`), bond payloads accept `master_id` (→ `bond_master`); the server snapshots name and symbol (stock: NSE symbol if exchange is NSE, else BSE symbol) or name and ISIN (bond). Stock/bond holdings keep what the user sent for issuer, face value, maturity and bond type.
- **Cron:** `GET /api/cron/securities` (bearer `CRON_SECRET`), Vercel `0 14 * * *` UTC (19:30 IST). Runs both imports; response is `{stocks: {...}, bonds: {...}}`. CLI: `python -m app.jobs.securities_import`.

### Master data (FD/RD issuers)

- **`fd_issuer_master`** (global, no `user_id`; model `api/app/models/fd_issuer_master.py`, migration 0011; service `api/app/services/fd_issuers.py`, whose module docstring lists the sources): id, code UNIQUE, name, short_name?, category, regulator?, reg_no?, dicgc_insured (`true` when matched, else NULL), accepts_deposits, merged_into_id? (self FK, ON DELETE SET NULL), merged_on?, is_active, last_seen, sources (internal tags), updated_at. Trigram index on lower(name).
- **Categories:** `public_sector`, `private_sector`, `small_finance`, `foreign`, `regional_rural`, `local_area`, `payments`, `state_coop`, `district_coop`, `urban_coop` (banks, from the Razorpay type: PSB, Private, SFB, Foreign, RRB, LAB, PB, SCB, DCCB, S-UCB/O-UCB), `nbfc`, `hfc`, `post_office`.
- **Codes:** banks use the Razorpay IFSC bank key (e.g. `BARB`); NBFCs `NBFC:<slug>`, HFCs `HFC:<slug>`; India Post `POST`.
- **accepts_deposits:** false for payments banks (`payments`), RBI (`RBIN`) and the General Post Office (`GPOX`), which Razorpay lists as public-sector banks. NBFC/HFC rows: false only for `not_permitted`; `permitted` and `prior_approval` are true.
- **Sources** (tags in `sources`; each optional, a failure is recorded and never aborts the others):
  - `razorpay`: razorpay/ifsc `banks.json` (latest GitHub release, with the release download URL as fallback) for type, and `banknames.json` (master branch) for names. Bank rows. MIT licensed.
  - `dicgc`: DICGC "list of active insured banks" xlsx. The link is scraped weekly from https://www.dicgc.org.in/insured-banks and the file is parsed with the standard library (no new dependency). Sets `dicgc_insured = true` on matched banks. Exact normalised name or override matches first (any DICGC sheet). Then a conservative fuzzy match, only for co-op banks and RRBs, only within the matching DICGC sheet (UCBs, State Co-op Banks, DCCBs, RRB): similarity ratio ≥ 0.92, margin over the next candidate ≥ 0.05, and unique (two banks claiming one name are both rejected).
  - `seed_banks`: `api/data/fd_issuer_bank_aliases.csv` (90 rows): short names, 17 mergers (`merged_into_code`, `merged_on`; merged banks are inactive and point at the surviving bank), 20 DICGC name overrides. Seed codes may be banks.json keys or IFSC prefixes.
  - `seed_nbfc`: `api/data/fd_issuers_nbfc_hfc.csv`: 16 deposit-taking NBFCs and 11 HFCs (`deposit_status` permitted / prior_approval / not_permitted), each with a cited source column (bankzop NBFC directory, RBI NBFC list, NHB list of HFCs). Refreshed by hand.
  - `fixed`: India Post (`POST`, `post_office`), always present.
- **Upsert and activity:** rows are upserted only when something changed, never deleted. Bank rows missing from a successful Razorpay run deactivate after a 30-day grace (`STALE_DAYS`); NBFC/HFC rows deactivate as soon as they leave the seed. If Razorpay fails, bank rows are not touched.
- **Holdings link:** FD and RD payloads accept `issuer_id` (nullable). The server snapshots `bank` = `short_name`, or `name` when there is no short name (≤ 200 chars). An unknown id or an issuer with `accepts_deposits` false is a 422 on `issuer_id` (§2 rule 20). Merged and inactive issuers are still accepted, so old holdings stay valid. Manual entries keep `issuer_id` null and the typed bank text.
- **Search order** (`GET /master/fd-issuer`, §4): the query must be ≥ 2 characters. Every token must match name, short name or code (case-insensitive). Deposit-taking issuers only; merged and inactive ones are included so old holdings stay findable. Order: category (`public_sector`, `private_sector`, `small_finance`, `foreign`, `nbfc`, `hfc`, `post_office`, `regional_rural`, `local_area`, `state_coop`, `urban_coop`, `district_coop`, then any other), then trigram similarity of name to the query, then name, then id.
- **Known gaps:** Unity Small Finance Bank is only in Razorpay's `banknames.json` (not `banks.json`), so it is not listed; enter it manually. Razorpay RRB names are pre-amalgamation. NBFC and HFC `reg_no` is empty (CoR numbers not obtained; RBI files block automated access and the NHB page has none).
- **Cron:** `GET /api/cron/issuers` (§4), weekly. CLI: `python -m app.jobs.issuers_import`.

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
| 13 | Bond `invested_amount` must equal quantity × purchase_price: \|quantity × price − total\| ≤ quantity × 0.005 + 0.01 (field `invested_amount`) | Total invested must equal quantity × purchase price |
| 14 | ISIN (optional): uppercased, `^[A-Z]{2}[A-Z0-9]{9}[0-9]$` | ISIN must be 12 characters, e.g. INE002A01018 |
| 15 | Symbol (optional): uppercased, `^[A-Z0-9&-]{1,20}$` | Symbol: letters, digits, & or -, up to 20 characters |
| 16 | Text ≤ 200 chars (names, bank, label, issuer, broker, platform, scheme); notes ≤ 1000 | Must be at most N characters |
| 17 | MF `scheme_code` (optional) must exist in `mf_master` | Select a scheme from the list |
| 18 | Stock `master_id` (optional) must exist in `stock_master` | Select a stock from the list |
| 19 | Bond `master_id` (optional) must exist in `bond_master` | Select a bond from the list |
| 20 | FD/RD `issuer_id` (optional) must exist in `fd_issuer_master` and accept deposits | Select a bank or issuer from the list |
| P | Payout FD cannot use `simple` | Choose a payout frequency |
| A1 | Auth email (sign-up and login): trimmed, lower-cased, address shape, ≤ 320 chars | Enter a valid email address |
| A2 | Sign-up password: 10–128 characters (login only requires non-empty, "Required") | Password must be at least 10 characters / Password must be at most 128 characters |

MF scheme picker: the form requires a scheme in picker mode; "Not listed? Enter manually" allows free text with a null `scheme_code`. When a code is set, the server snapshots `scheme_name` from the master.

FD/RD issuer picker: the form requires an issuer in picker mode (rule 20); "Not listed? Enter manually" switches to free text, where bank is required ("Required") and `issuer_id` is null.

No minimum amounts beyond > 0 (user decision). Cross-field errors are attached to a field: tenure → `tenure_years`, payout frequency → `compounding`, invested total → `invested_amount`, maturity rules → `maturity_date`. Read models accept existing rows even if they'd fail new create-time rules.

## 3. Valuation (server side, `valuation.py`)

Year fraction = days / 365. Rates are percent. Periods/yr: monthly 12, quarterly 4, half_yearly 2, yearly 1.

- **Maturity date** (FD, RD) = start + relativedelta(years, months) + days. **Status** = `matured` if today ≥ maturity else `active` (bond: from maturity_date).
- **FD cumulative**: invested = principal; current = P × (1 + r/n)^(n·t), `simple` → P × (1 + r·t); t from start to min(today, maturity).
- **FD payout** (`payout_type = payout`; `compounding` holds the payout frequency): invested = current = principal; `interest_received` = P × r/n × completed payout periods (period ends every 12/n months after start, ≤ min(today, maturity)); if matured, plus the final partial period up to maturity (total = simple interest over the tenure). gain = interest_received.
- **RD**: instalments on start + k months while date < maturity and ≤ today (assumed paid on time); invested = count × instalment; current = Σ each instalment compounded (same rule) to min(today, maturity).
- **Bond**: invested = `invested_amount` (the stored total); current = invested × (1 + ytm/100)^t, t from purchase to min(today, maturity). face_value is display-only.
- **Stock**: invested = qty × avg_buy_price; current = invested (no price API yet).
- **MF**: invested = units × avg_nav. If `scheme_code` is set and the scheme has a row in `mf_nav_latest`, current = units × latest NAV (used even if stale); otherwise (manual entry, or no NAV) current = invested.
- gain = current − invested (payout FD: interest_received); gain_pct = gain / invested × 100. Group and dashboard totals SUM item gains (not current − invested). Outputs rounded to 2 dp.
- **Matured holdings are closed**: they still appear in `items` (status Matured) but are excluded from every total (group totals, dashboard totals/allocation, holdings `summary`) and from `count`. `matured_count` reports how many were excluded.

Reference checks: FD 100000 @ 7% quarterly, start 2025-10-24, 1y, on 2026-10-24 → 107185.90. Payout FD 100000 @ 7.2% quarterly 1y → 3600.00 after 2 quarters, 7200.00 at maturity. Bond 10 × 1000, ytm 8, 1 year → 10800.00.

## 4. API (prefix `/api`, snake_case JSON, decimals as numbers)

- `GET /health` → `{"status":"ok"}` (no API key needed).
- `GET /master/mf?q=&limit=20` → active schemes from `mf_master` with nav and nav_date. `q` ≥ 2 characters; every token must match; ranked by trigram similarity.
- `GET /master/mf/{scheme_code}` → one scheme (with nav and nav_date); 404 "Scheme not found".
- `GET /master/mf/{scheme_code}/nav?date=YYYY-MM-DD` → `{scheme_code, requested_date, nav_date, nav, source: latest|history}`. Returns the last NAV on or before the date (weekends and holidays resolve to the previous trading day).
  - 404 "Scheme not found"
  - 404 "NAV not available" / "No NAV published on or before this date." (also for dates older than 10 years)
  - 422 "Invalid date" ("Date: Date cannot be in the future")
  - 502 "Couldn't fetch NAV history"
- `GET /master/stock?q=&limit=20` → active stocks and ETFs from `stock_master`. `q` ≥ 2 characters; tokens are ANDed over name, NSE/BSE symbol, BSE code, ISIN and issuer; ranked by trigram similarity on name.
- `GET /master/stock/{id}` → one stock or ETF; 404 "Stock not found" / "The requested resource doesn't exist."
- `GET /master/bond?q=&limit=20` → active bonds from `bond_master`, same search rules.
- `GET /master/bond/{id}` → one bond; 404 "Bond not found" / "The requested resource doesn't exist."
- `GET /master/fd-issuer?q=&limit=20` → deposit-taking banks, NBFCs, HFCs and India Post from `fd_issuer_master`; `limit` 1–50. `q` ≥ 2 characters (else `[]`); search and ranking rules in §1.
- `GET /master/fd-issuer/{id}` → one issuer (with `merged_into` when set); 404 "Issuer not found" / "The requested resource doesn't exist."
- `GET /cron/amfi` → runs the AMFI import and returns counts. No X-API-Key; requires `Authorization: Bearer $CRON_SECRET`. Vercel Cron runs it daily at `30 16 * * *` UTC (22:00 IST).
- `GET /cron/securities` → runs the stock and bond master imports (see Master data). Same bearer auth; Vercel Cron `0 14 * * *` UTC. Returns `{stocks: {...}, bonds: {...}}`.
- `GET /cron/issuers` → runs the FD/RD issuer master import (§1) and returns its counts. Same bearer auth; Vercel Cron `0 3 * * 1` UTC (Mondays 08:30 IST, weekly). 502 "Couldn't fetch the issuer files" when both the Razorpay and DICGC sources fail.
- `GET|POST /assets/{type}`, `GET|PUT|DELETE /assets/{type}/{id}`; PUT is a full replace.
- `GET /portfolio` → `{groups:[{type,label,items[],totals{invested,current_value,gain,gain_pct},count,matured_count}]}` (totals and count cover active holdings only) — always 5 groups in order fd, rd, stock, bond, mf. Items = record fields + `invested, current_value, gain, gain_pct, status`, plus `maturity_date` (fd/rd/bond), `interest_received` (payout FD), and `nav` + `nav_date` (mf: latest NAV, 4 dp, and its date; null when no NAV). The NAV lookup is one extra query over held schemes only.
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
  - Item: record fields + `invested, current_value, gain, gain_pct, status`, plus `maturity_date` (fd/rd/bond), `interest_received` (payout FD), and `nav` + `nav_date` (mf).
- Auth: if `API_KEY` env is set, every route except `/api/health`, `/api/cron/amfi` (bearer `CRON_SECRET` instead) and OPTIONS needs header `X-API-Key` (401 otherwise).
- Sign-in: every route except `/api/health`, `/api/cron/*`, `/api/auth/*` and OPTIONS needs `Authorization: Bearer <access token>` (401 otherwise). Holdings are per user; see §7.

### Message contract (toasts render these verbatim)
- POST 201 → record + `message` ("Fixed deposit added" / "Recurring deposit added" / "Stock added" / "Bond added" / "Mutual fund added") + `description` (holding name: FD/RD bank[ · label], stock/bond name, MF scheme_name).
- PUT 200 → record + `message: "Changes saved"` + description.
- DELETE **200** → `{message: "<Type> deleted", description}`.
- Errors always: `{message, description, detail}`. 422 → "Couldn't save — check the highlighted fields" + first field error ("Principal: Must be at most ₹100 crore"), `detail` = list of {loc,msg,type}. 422 on `GET /holdings/*` → "Invalid filters" + first error. 404 → "<Type> not found" / "It may have been deleted already." 401 → "Not authorised" / "Your session may have expired. Log in again." 500 → "Something went wrong on the server" (+ error class only). Other HTTP errors → "Request failed".
- Next.js proxy's own errors use the same shape: 401 "Not logged in" / "Log in to continue." (no session cookies), 502 "Couldn't reach the server", 400 "Bad request".
- Auth outcomes (`/api/auth/*`, details in §7):
  - 201 signup → tokens + `user`; 200 login/refresh → tokens + `user`; 200 logout → "Logged out" / "You have been logged out."
  - 403 signup → "Sign-ups are invite-only" / "This email isn't on the invite list."
  - 409 signup → "An account with this email already exists" / "Log in instead."
  - 401 login (unknown email and wrong password alike) → "Incorrect email or password" / "Check your details and try again."
  - 429 login → "Too many attempts" / "Wait 15 minutes and try again."
  - 422 on any `/api/auth/*` → "Check the highlighted fields" + first field error (rules A1, A2 in §2).
  - 401 refresh, or any route with a missing/invalid/expired access token → "Not authorised" / "Your session may have expired. Log in again."

## 5. Web app

- Pages: `/` Dashboard (KPI cards, holdings-by-type table with allocation bars; asset-type rows link to `/portfolio/{type}`).
  - `/portfolio` redirects to the first asset type you hold.
  - `/portfolio/{type}` shows Groww-style fixed-width tabs (FD, RD, Stocks, Bonds, Mutual Funds, with counts) and a sliding underline. The content fades in when the type changes; reduced motion is respected.
  - Each type has a summary strip (count, invested, current, gain) and an "Add FD"/"Add RD"/"Add stocks"/… button linking to `/add/{type}`.
  - Its own grid has type-specific columns and filters. Stocks include Current/Gain/Gain %, which equal invested and 0 until live prices exist. MF Current/Gain use the latest NAV where available (see §3). The MF grid has a visible-by-default, non-sortable "NAV" column after Avg NAV: latest NAV with a muted "as of {date}" line, "—" when null.
  - The grid has debounced search, faceted filters, %-range and maturity-date range filters, Reset, and a Columns menu saved per type in localStorage `wt.portfolio.columns.{type}`.
  - Sortable headers; 10 rows per page; no totals row.
  - Row actions: eye (disabled, "Details coming soon"; future `/portfolio/{type}/{id}`) and ⋯ Edit/Delete.
  - State lives in the URL. Breadcrumb reads `Portfolio › {type label}`.
- `/add` (gallery of asset-type tiles grouped Deposits / Market-linked, each with an "N held" count from `/api/dashboard`; registry in `web/lib/asset-catalog.ts`), `/add/{fd|rd|stock|bond|mf}` (form for that type; back link to `/add`; save → `/portfolio/{type}` (that type's tab), cancel → `/add`; unknown type → 404; legacy `/add?type=x` redirects to `/add/x`), `/login`, `/signup` (both without the sidebar).
- Browser calls only same-origin `/api/*`; `app/api/[...path]/route.ts` forwards to `API_URL` with `X-API-Key`.
- Sign-in is required everywhere, local dev included: `proxy.ts` redirects pages without the `wt_refresh` cookie to `/login?next=…`; cookies, refresh and the proxy rules are in §7. The top bar, right of the "Add asset" button, has an account menu (`web/components/user-menu.tsx`): a round avatar with the email's first letter (from `GET /api/me`) opens a dropdown with "Signed in as <email>" and "Log out".
- MF form (`components/forms/scheme-picker.tsx`): scheme picker is a server search over `/api/master/mf`, showing AMC · Plan · Option and the latest NAV. Picking sets the name and category (category stays editable). "Not listed? Enter manually" switches to free text.
- Stock form (`components/forms/stock-form.tsx`, picker from `components/forms/master-picker.tsx`): picker by default ("Search stocks and ETFs…"; rows show name, NSE/BSE symbols, ISIN, ETF badge). Picking sets name, symbol and the exchange default; changing the exchange re-derives the symbol. "Not listed? Enter manually" switches to free text; "Search the stock list instead" switches back.
- Bond form (`components/forms/bond-form.tsx`): picker ("Search bonds…"; rows show name, ISIN · type · coupon · maturity). Picking sets name, ISIN, issuer, bond type and maturity date (always), and fills purchase price (issue price, else face value), YTM (coupon rate) and purchase date (issue date, if not in the future) only when those are empty. All stay editable.
- Bond amounts: enter any two of Quantity, Purchase price per unit and Total invested; the third is calculated (price = total ÷ quantity, 2 dp; total = quantity × price; quantity = total ÷ price, rounded to a whole number). Pure helper `web/lib/bond-amounts.ts`, unit tests `web/lib/bond-amounts.test.ts` (`cd web && npm test`). Face value is not an input.
- FD tenure: the FD form takes either Duration (years, months, days) or a Maturity date ("Duration / Maturity date" toggle). A maturity date is converted to years, months and days; the same §2 rules apply.
- FD and RD forms (`components/forms/fd-form.tsx`, `rd-form.tsx`): "Bank / issuer" picker (shared `components/forms/issuer-picker.tsx`, a server search over `/api/master/fd-issuer`; rows show the short name or name, the category, "DICGC insured" and "Merged into" when set). Picking sets `issuer_id` and copies the short name (or name) into Bank. "Not listed? Enter manually" switches to free text ("Search the bank list instead" switches back). New holdings open in picker mode; existing holdings without an issuer link open in manual mode. Editing loads the linked issuer from `/master/fd-issuer/{id}`, and falls back to the stored bank text if that fails.
- Edit dialog for stocks/bonds shows the linked security (fetched from `/master/stock/{id}` or `/master/bond/{id}`).
- MF Average NAV auto-fill (`components/forms/use-nav-autofill.ts`): once a scheme and purchase date are set, Average NAV fills from `/api/master/mf/{scheme_code}/nav` with the hint "NAV on {date} · AMFI". It stays editable and never overwrites a value the user typed. Errors show the API message as a muted hint.
- Inputs: money/quantity/units use Indian digit grouping while typing (`components/forms/number-format.ts`); dates via themed DateField (Popover + Calendar, Monday first, month/year custom dropdowns, days outside allowed range disabled); payout FDs relabel Compounding → "Payout frequency" without Simple.
- Toasts (sonner, themed): title = API `message`, description = API `description`.
- Theme: dark only, zinc palette, emerald primary, Geist Sans/Mono, root font-size 110%, sidebar 13.5rem.

## 6. Environment variables

| Where | Var | Notes |
|---|---|---|
| api | `DATABASE_URL` | Neon pooled string (`postgresql://…?sslmode=require`; normalised to psycopg3) |
| api | `API_KEY` | optional locally; required in production |
| api | `CRON_SECRET` | production (`openssl rand -hex 32`); bearer token for `/api/cron/amfi` |
| api | `JWT_SECRET` | required for sign-in (`openssl rand -hex 32`); signs access tokens; missing → login/refresh fail with 500 |
| api | `ALLOWED_EMAILS` | comma-separated sign-up allowlist (case-insensitive); empty = nobody can sign up |
| api | `OWNER_EMAIL` | read only by migration 0010 (owner of pre-auth holdings; GitHub `production` secret in CI); not used at runtime |
| api | `GOOGLE_CLIENT_ID` | Google sign-in (OAuth client, type Web application); with the secret below, else `/auth/google` → 503 |
| api | `GOOGLE_CLIENT_SECRET` | Google sign-in; used only for the server-side code exchange |
| api | `CORS_ORIGINS` | default `["http://localhost:3000"]`; not needed in production (proxy) |
| web | `API_URL` | FastAPI origin, no trailing slash, no `/api` (default http://localhost:8000) |
| web | `API_KEY` | same value as api |
| web | `GOOGLE_CLIENT_ID` | Google sign-in; same client ID as the api. Unset → the Google button returns "isn't configured" |
| web | `APP_ORIGIN` | optional public origin (e.g. `https://app.example.com`) used for the Google redirect URI; default is the request origin |

## 7. Auth

Users sign in with email and password. Every holding belongs to one user.

### Data (migration 0010)

- **`users`** (model `api/app/models/user.py`): id, email (unique, lower-cased, ≤ 320), password_hash (argon2id; NULL = no password set yet), google_sub (unique, nullable; migration 0012; Google's stable user id), is_active, last_login_at, created_at, updated_at.
- **`refresh_tokens`** (`refresh_token.py`): id, user_id (FK, ON DELETE CASCADE), family_id (shared by every token rotated from one sign-in), token_hash (SHA-256; the raw token is never stored), expires_at, revoked_at, replaced_at, created_at.
- **`login_attempts`** (`login_attempt.py`): id, email, attempted_at, succeeded. Feeds the rate limit.
- **Holdings:** `fixed_deposits`, `recurring_deposits`, `stocks`, `bonds`, `mutual_funds` each have `user_id` (NOT NULL, FK → users, ON DELETE CASCADE).
- Master tables (`mf_master`, `mf_nav_latest`, `mf_nav_history`, `stock_master`, `bond_master`) stay global, with no `user_id`.

### Scoping

- Every holdings route (`/assets/*`, `/holdings/*`, `/portfolio`, `/dashboard`) reads and writes only the signed-in user's rows. Another user's id gives the usual 404 (e.g. "Fixed deposit not found").
- Master routes (`/master/*`) are global but need sign-in.
- Cron routes and `/health` are unchanged (no user).

### Endpoints (`/api`)

- `POST /auth/signup` `{email, password}` → 201. Email must be on `ALLOWED_EMAILS` (else 403); an existing email gives 409. Creates the user and signs in.
- `POST /auth/login` `{email, password}` → 200. Unknown email and wrong password give the same 401. Rehashes the password if the hash parameters changed.
- `POST /auth/google` `{code, code_verifier, redirect_uri}` → 200 token response. Called server-side by the web callback only (see "Sign in with Google"). Field errors are 422 with "Required", "Invalid code verifier" or "Invalid redirect URI".
- `POST /auth/refresh` `{refresh_token}` → 200 with a new pair (old token rotated).
- `POST /auth/logout` `{refresh_token}` → 200 "Logged out", whether or not the token is known. Revokes the token's whole family.
- `GET /auth/me` (Bearer) → `{id, email}`.
- Token response: `{access_token, access_expires_at, refresh_token, refresh_expires_at, user: {id, email}}`.

### Tokens and limits

- **Access token:** JWT, HS256 signed with `JWT_SECRET`, valid 15 minutes. Claims: `sub` (user id), `email`, `typ: access`, `iat`, `exp`. Checked on every request; an inactive user gets 401.
- **Refresh token:** opaque random string, valid 30 days, stored hashed. Every use rotates it. Reusing a rotated token within 60 s returns a fresh pair (covers parallel requests). Reusing it after 60 s revokes the whole family (assumed theft) and returns 401. Unknown, expired, revoked or inactive → 401.
- **Rate limit:** 5 failed logins for one email within 15 minutes → 429 for that email. Successful logins do not count. Google sign-ins are not counted at all.
- **Passwords:** argon2id. Sign-up requires 10–128 characters (rule A2 in §2).

### Sign in with Google

- The "Continue with Google" button (`web/app/(auth)/auth-form.tsx`, on `/login` and `/signup`) links to `GET /auth/google/start?next=<path>`.
- **Start** (`web/app/auth/google/start/route.ts`): creates a random `state` and PKCE `code_verifier`, stores both with `next` in the httpOnly cookie `wt_oauth` (path `/auth/google`, 10 min), and redirects to Google: scope `openid email profile`, `prompt=select_account`, `code_challenge_method=S256`. Redirect URI: `<APP_ORIGIN or request origin>/auth/google/callback`.
- **Callback** (`web/app/auth/google/callback/route.ts`): fails if Google returned `error`, or if `code`/`state` is missing or `state` does not match the cookie. Otherwise it calls `POST /api/auth/google` server-side with `{code, code_verifier, redirect_uri}`. On success it sets `wt_access` and `wt_refresh` as for password sign-in and redirects to `next`. It always clears `wt_oauth`. Browsers never call the endpoint directly.
- **API** (`api/app/services/google_auth.py`, `POST /auth/google`): exchanges the code at Google's token endpoint with `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and the verifier. It verifies the ID token against Google's JWKS (RS256; `aud` = `GOOGLE_CLIENT_ID`; `iss` = `accounts.google.com`; `exp`, 30 s leeway) and requires `email_verified` to be true.
- **Account resolution:** same `google_sub` → sign in. Else an existing user with the same email → link it (sets `google_sub`; refused if the account is already linked to another Google identity). Else an email on `ALLOWED_EMAILS` → create the user with no password. Else 403. A deactivated account gets 401 "Incorrect email or password". Success returns the same token pair as the other endpoints.
- Google-only accounts have no password. Set one with `cd api && .venv/bin/python -m app.jobs.users set-password --email <email>`.
- `web/proxy.ts` lets `/auth/google/start` and `/auth/google/callback` through without a session.
- Errors: the web renders the API `message` and `description`, or the fallback below. The callback passes them to `/login` in the httpOnly cookie `wt_auth_error` (path `/`, 60 s), which the login and signup pages show inline. A network failure to the API shows "Couldn't reach the server".

| Status | Message | Description | When |
|---|---|---|---|
| 503 | Google sign-in isn't configured | Use your email and password for now. | `GOOGLE_CLIENT_ID` (web) or `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` (api) unset |
| 401 | Google sign-in failed | Try again, or log in with your email. | State mismatch or missing cookie; code exchange or ID token check fails; account linked to another Google identity; database conflict. Also the web fallback. |
| 403 | Google email not verified | Verify your email with Google, then try again. | Google reports `email_verified` false |
| 403 | Sign-ups are invite-only | This email isn't on the invite list. | New Google email not in `ALLOWED_EMAILS` (same text as email sign-up) |
| 401 | Incorrect email or password | Check your details and try again. | Deactivated account (same text as email sign-in) |

### Web

- Cookies `wt_access` (15 min) and `wt_refresh` (30 days): httpOnly, SameSite=Lax, path `/`, Secure in production. Set by the login and signup server actions (`web/app/actions/auth.ts`) from the API response; the browser never reads the tokens.
- `web/proxy.ts`: pages without `wt_refresh` redirect to `/login?next=<path>`. `/login` and `/signup` with a `wt_refresh` cookie redirect to `/`. `/api/*` without `wt_refresh` returns 401 "Not logged in".
- `web/app/api/[...path]/route.ts`: sends `Authorization: Bearer` from `wt_access`. It refreshes proactively when the access token is missing, unreadable or expires within 30 s, and otherwise refreshes once on an upstream 401 and retries. Refreshed cookies go on the response. If refresh fails, it returns 401 "Not authorised" and clears both cookies. It also maps `GET /api/me` to `/api/auth/me`.
- The browser cannot call `/api/auth/*` directly: the route handler returns 404 for it (auth goes through the server actions only).
- `/login` and `/signup` are the only auth pages. `next` is honoured only for same-origin relative paths. Log out (account menu in the top bar) revokes the refresh family and clears both cookies, then goes to `/login`.
- The login and sign-up password fields have a show/hide (eye) toggle.

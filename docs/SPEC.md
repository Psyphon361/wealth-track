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
| Mutual Fund (`mf`) | `mutual_funds` | scheme_code? (FK → `mf_master.scheme_code`), scheme_name, platform?, category (`equity`\|`debt`\|`hybrid`\|`index`\|`elss`\|`liquid`\|`other`), units (3 dp), avg_nav (4 dp), invested_amount (total invested; NOT NULL; migration 0015, backfilled as round(units × avg_nav, 2)), purchase_date |
| Gold & Silver (`gold`) | `gold_holdings` | name, metal (`gold`\|`silver`; default gold; migration 0022), form (`jewellery`\|`coin`\|`bar`\|`digital`), purity (gold: `999`\|`995`\|`916`\|`750`\|`585`, labels 24K (999), 24K (995), 22K (916), 18K (750), 14K (585); silver: `999` (fine), `925` (sterling); must fit the metal), weight_grams (3 dp), purchase_date, invested_amount (value on the purchase day, excluding making charges and GST; NOT NULL). No master link. Silver ETFs and funds stay under Stocks/MF. |
| Cash & Savings (`cash`) | `cash_holdings` | name, kind (`savings`\|`current`\|`cash`\|`other`; labels Savings account, Current account, Cash in hand, Other), balance (NOT NULL; money > 0), interest_rate? (% p.a., optional; informational only, not used in any money maths), balance_date (the date the balance was read). No master link; migration 0020. |
| EPF & PPF (`pf`) | `pf_holdings` | name, kind (`epf`\|`vpf`\|`ppf`; labels EPF, VPF, PPF), balance (NOT NULL; money > 0), balance_date (the date the balance was read), interest_rate (% p.a., required, 0–15%; used in the value), contributed? (total deposited; optional; invested when set), opened_on? (PPF opening date; required for PPF, dropped for EPF/VPF). No master link; migration 0021. |
| NPS (`nps`) | `nps_holdings` | scheme_id (FK → `nps_master.scheme_id`; required, rule N1), units (4 dp), contributed (total contributed; money), start_date (rule N4). No snapshot: scheme name, PFM, tier and class come from the master. Migration 0024. |
| Other (`other`) | `other_holdings` | name, category (free text, trimmed, ≤ 40 chars; e.g. Crypto), current_value (NOT NULL; money > 0; entered by hand), value_date (NOT NULL; the date the value was read), invested_amount? (amount invested; optional), acquired_on? (purchase date; optional). No price tracking and no master link; migration 0026. |

Column precision: money Numeric(14,2), rate/ytm Numeric(6,3) (input limited to 2 dp), units Numeric(14,3), avg_nav Numeric(14,4), gold weight_grams Numeric(12,3), gold rate_per_gram Numeric(12,2), NPS units and nav Numeric(14,4). Enums are VARCHAR + CHECK (not native PG enums).

Removed by user decision: FD maturity amount & status inputs, stock current price (future API), MF AMC/folio/plan/option, bond coupon rate/frequency (YTM used instead). MF SIPs were removed at first and are back (§8a).

### Master data (MF)

- **`mf_master`** (static; daily upsert writes only rows that changed; renamed from `mf_schemes` in migration 0007, metadata-only): scheme_code PK, name, amc, amfi_category, category (mapped to the app enum), plan (direct/regular), option (growth/idcw/bonus/other), idcw_frequency, isin_growth_payout, isin_reinvest, is_active, updated_at. Model `MFMaster` (`api/app/models/mf_master.py`).
- **`mf_nav_latest`:** scheme_code PK/FK, nav (4 dp), nav_date. One current NAV per scheme.
- **Source:** AMFI `https://portal.amfiindia.com/spages/NAVAll.txt`. A scheme is active if its NAV date is within 30 days of the file's latest date. Rows are never deleted.
- **Plan and option enrichment:** the same import also downloads AMFI's scheme master CSV (`https://portal.amfiindia.com/DownloadSchemeData_Po.aspx?mf=0`). Where NAVAll.txt leaves plan or option blank and the scheme name doesn't say, it takes them from the CSV's "Scheme NAV Name" column (about 5,400 of 14,400 schemes). Non-blank NAVAll columns win. If the CSV fetch fails, the import still runs without it. ETFs, FMPs and interval funds often have no plan, which stays null. The result and job output report `scheme_data_loaded` and `from_scheme_data` (the job prints `plan_or_option_from_scheme_data`).
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

### Master data (gold rates)

- **`gold_rate_latest`** (metal + purity PK, rate_per_gram, rate_date, session `AM`|`PM`, source, updated_at; one row per metal and purity) and **`gold_rate_history`** (metal + purity + rate_date PK, rate_per_gram). Global, no `user_id`. Models `api/app/models/gold_rate.py`, migrations 0018 and 0022 (`metal` added to both keys; existing rows are gold).
- **Source:** IBJA rates from `https://ibjarates.com/`. The gold AM and PM tables are per 10 g and are divided by 10 to give rupees per gram; PM overrides AM for the same date. Rows are keyed by the date the page states, so weekends and holidays keep the last published rate. Parser and importer: `api/app/services/gold_rates.py`.
- **Silver:** the same page's Silver 999 rate is per kg; the importer stores it per gram (÷ 1000). Silver 925 is never stored: read helpers derive it as the 999 rate × 925 / 999, rounded to 0.01. A page without a silver row still imports gold.
- **Cron:** `GET /api/cron/gold` (bearer `CRON_SECRET`), Vercel `0 13 * * *` UTC (18:30 IST). CLI: `python -m app.jobs.gold_import`.
- **Nightly gap fill:** the import also fills missed dates from the homepage's hidden `HdnGold` / `HdnSilver` fields (about 4 months of PM rates: gold 999 and 916, silver 999). It only inserts missing `gold_rate_history` rows, never overwrites.
- **History backfill** (one-time, re-runnable, only inserts missing rows): `python -m app.jobs.gold_backfill` (`api/app/services/gold_history.py`). Sources:
  - ibja.co daily report PDFs from 10 May 2022 on.
  - The Wayback Machine snapshot of ibjarates.com for 1 Jan 2014 to 14 Feb 2018: gold 999 and silver 999; other gold purities derived with ratios 0.996, 0.916, 0.750 and 0.585.
  - 15 Feb 2018 to 9 May 2022 is deliberately empty: there is no free daily IBJA source. A purchase in that gap (or before 2014) has no rate, so its invested amount must be entered by hand, and net worth values it at cost there.
  - Known holes after 10 May 2022 (dev backfill, 2026-11-02): 109 weekdays have no report PDF (mostly holidays) and 7 PDFs are unreadable (2023-07-27, 2023-07-28, 2025-10-08 to 2025-10-14). 51 of the missing days were filled with gold 999 and silver 999 only, from the 5-day table in nearby reports. Any date without a rate in the last 7 days falls back to cost in net worth.
  - Runs via the manual workflow `.github/workflows/gold-backfill.yml` (inputs: `target` dev|prod, `source` all|pdf|wayback, optional `from` / `to`).

### Master data (NPS)

- **`nps_master`** (static; daily upsert; model `api/app/models/nps_master.py`, migration 0023): scheme_id PK (`SM…` ids), pfm_code (`PFM…`), pfm_name, scheme_name, tier (`I`\|`II`, from the name), asset_class (`E`\|`C`\|`G`\|`A`\|`other`, from the name), is_active, updated_at. Trigram index on lower(scheme_name). Ids missing from the file become inactive; rows are never deleted.
- **`nps_nav_latest`** (one row per scheme: nav 4 dp, nav_date), **`nps_nav_history`** (scheme_id + nav_date PK, nav) and **`nps_nav_history_sync`** (scheme_id PK, synced_at; one row once a scheme's history backfill has run). Global, no `user_id`.
- **Source:** NPS Trust `https://npstrust.org.in/nav-report-excel` (all schemes, latest NAV, TSV). The PFM code is not in that file; it is derived from the scheme id (`SM<NNN>…` → `PFM<NNN>`). Parser and importer: `api/app/services/nps.py` (module docstring lists the sources).
- **History:** per held scheme from `scheme-wise-nav-report-excel`, back to 2009. The response mixes other schemes' rows, so only the requested scheme's rows are kept. Backfilled once in the background after a holding is created or updated (`sync_scheme_safely`); the nightly import retries unsynced held schemes and appends today's NAV for held schemes.
- **Cron:** `GET /api/cron/nps` (bearer `CRON_SECRET`), Vercel `45 16 * * *` UTC (22:15 IST). CLI: `python -m app.jobs.nps_import`. Dev data refresh workflow job `nps`.

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
| 21 | MF `invested_amount` must equal units × avg_nav: \|units × avg_nav − total\| ≤ units × 0.00005 + avg_nav × 0.0005 + 0.01 (field `invested_amount`) | Total invested must equal units × average NAV |
| G1 | Gold `metal` (gold or silver), `form` and `purity` must be from the lists; purity must fit the metal (silver: 999, 925) | Choose a metal / Choose a form / Choose a purity (missing metal → Required) |
| G2 | Gold `weight_grams` > 0, at most 3 dp, ≤ 1 crore | Must be greater than 0 / Weight can have at most 3 decimal places / Must be at most 1 crore |
| G3 | Gold `purchase_date` follows rules 7 and 8 | As rules 7 and 8 |
| C1 | Cash `kind` must be from the list | Choose an account type |
| C2 | Cash `balance` > 0 and at most ₹100 crore (rule 5); `interest_rate` (optional) follows rule 1 | Must be greater than 0 / Must be at most ₹100 crore / Interest rate must be between 0 and 15% |
| C3 | Cash `balance_date` follows rules 7 and 8 | As rules 7 and 8 |
| PF1 | PF `kind` must be from the list | Choose an account type |
| PF2 | PF `balance` > 0 and at most ₹100 crore (rule 5); `interest_rate` follows rule 1 (required); `contributed` (optional) > 0 and at most ₹100 crore | Must be greater than 0 / Must be at most ₹100 crore / Interest rate must be between 0 and 15% |
| PF3 | PF `balance_date` follows rules 7 and 8 | As rules 7 and 8 |
| PF4 | PPF `opened_on` is required (follows rules 7 and 8); it is dropped for EPF and VPF | Enter the opening date |
| N1 | NPS `scheme_id` is required and must exist in `nps_master` (422 on `scheme_id`) | Choose a scheme (missing); Choose a scheme (unknown) |
| N2 | NPS `units` > 0, at most 1 crore (rule 6), at most 4 dp | Must be greater than 0 / Must be at most 1 crore / Up to 4 decimal places allowed |
| N3 | NPS `contributed` follows the money rules (> 0, at most 2 dp, rule 5) | Must be greater than 0 / Up to 2 decimal places allowed / Must be at most ₹100 crore |
| N4 | NPS `start_date` follows rules 7 and 8 (as MF purchase date) | As rules 7 and 8 |
| O1 | Other `category` is required, trimmed, at most 40 characters | Required / Must be at most 40 characters |
| O2 | Other `current_value` > 0 and at most ₹100 crore (rule 5); `invested_amount` (optional) follows the same money rules | Must be greater than 0 / Must be at most ₹100 crore / Up to 2 decimal places allowed |
| O3 | Other `value_date` and `acquired_on` (optional) follow rules 7 and 8 | As rules 7 and 8 |
| O4 | Other `acquired_on` can't be after `value_date` (422 on `acquired_on`; checked only when both dates are valid) | Purchase date can't be after the value date |
| P | Payout FD cannot use `simple` | Choose a payout frequency |
| A1 | Auth email (sign-up and login): trimmed, lower-cased, address shape, ≤ 320 chars | Enter a valid email address |
| A2 | Sign-up password: 10–128 characters (login only requires non-empty, "Required") | Password must be at least 10 characters / Password must be at most 128 characters |

MF scheme picker: the form requires a scheme in picker mode; "Not listed? Enter manually" allows free text with a null `scheme_code`. When a code is set, the server snapshots `scheme_name` from the master.

FD/RD issuer picker: the form requires an issuer in picker mode (rule 20); "Not listed? Enter manually" switches to free text, where bank is required ("Required") and `issuer_id` is null.

No minimum amounts beyond > 0 (user decision). Cross-field errors are attached to a field: tenure → `tenure_years`, payout frequency → `compounding`, invested total → `invested_amount`, maturity rules → `maturity_date`. Read models accept existing rows even if they'd fail new create-time rules.

## 3. Valuation (server side, `valuation.py`)

Year fraction = (365 per whole calendar year from the start date, plus the days left after the last anniversary) / 365, so a leap day never inflates a full year (`_effective_days`; a 29 Feb start has its anniversary clamped to 28 Feb in a non-leap year; a span with no leap day is the plain day count). Rates are percent. Periods/yr: monthly 12, quarterly 4, half_yearly 2, yearly 1.

- **Maturity date** (FD, RD) = start + relativedelta(years, months) + days. **Status** = `matured` if today ≥ maturity else `active` (bond: from maturity_date).
- **FD cumulative**: invested = principal; current = P × (1 + r/n)^(n·t), `simple` → P × (1 + r·t); t from start to min(today, maturity).
- **FD payout** (`payout_type = payout`; `compounding` holds the payout frequency): invested = current = principal; `interest_received` = P × r/n × completed payout periods (period ends every 12/n months after start, ≤ min(today, maturity)); if matured, plus the final partial period up to maturity (total = simple interest over the tenure). gain = interest_received.
- **RD**: instalments on start + k months while date < maturity and ≤ today (assumed paid on time); invested = count × instalment; current = Σ each instalment compounded (same rule) to min(today, maturity).
- **Bond**: invested = `invested_amount` (the stored total); current = invested × (1 + ytm/100)^t, t from purchase to min(today, maturity). face_value is display-only.
- **Stock**: invested = qty × avg_buy_price; current = quantity × latest price when the holding is linked (`master_id`) and has a row in `stock_price_latest`; otherwise (manual stock, no master link, no price row) current = invested. Latest price is the nightly NSE/BSE bhavcopy close, stored in `stock_price_latest` (`source` = `bhavcopy`) by the securities import (cron 19:30 IST); a row is overwritten only by a newer close. A live intraday source is a possible later addition (Yahoo blocks server clients; an Upstox analytics token needs an Upstox account). Stock items carry `price`, `prev_close`, `day_change_pct`, `price_time` and `price_source`; `HoldingsResponse.prices_as_of` is set for stocks. The same import appends that night's close for held stocks to `stock_price_history` (migration 0017; one close per held stock per trading day). After a cron or CLI run, a one-time 12-month month-end backfill (NSE bhavcopy, BSE fallback) runs for held stocks without a `stock_price_history_sync` row (`python -m app.jobs.stock_history_backfill [--months 12]`).
- **MF**: invested = `invested_amount` (the stored total; within rule 21's tolerance of units × avg_nav). If `scheme_code` is set and the scheme has a row in `mf_nav_latest`, current = units × latest NAV (used even if stale); otherwise (manual entry, or no NAV) current = invested. `prev_nav` / `prev_nav_date` = the stored `mf_nav_history` NAV on the latest date strictly before the current NAV date (DB only, no network); `day_change` = units × (nav − prev_nav) (2 dp), `day_change_pct` = (nav / prev_nav − 1) × 100 (2 dp); all null when nav or prev_nav is missing.
- **MF XIRR**: computed for the MF grid (an "XIRR" column after Gain %, sortable, nulls last) and the holding details page; grid rows carry `xirr`, `xirr_basis` and `xirr_transactions` (transactions loaded in one query); /api/portfolio and /api/dashboard don't; rules in §5.
- **Gold & Silver**: invested = `invested_amount` (value on the purchase day, excluding making charges and GST). Current = weight × latest IBJA rate for the metal and purity (`gold_rate_latest`, shown with `rate_date`; silver 925 uses the derived rate, see Master data); with no rate, current = invested and `rate_per_gram` / `rate_date` are null. XIRR is one cash flow: −invested on the purchase date, +current value today. Net worth uses the rate on or before each date (`gold_rate_history`), but only if it is at most 7 days old (the same limit as the gold form); with no such rate the holding counts at cost.
- **Cash & Savings**: invested = current = `balance`; gain 0, gain_pct 0, xirr null. Always active (never matures). `interest_rate` is shown on the form and grid only.
- **EPF & PPF**: current = balance + simple interest at `interest_rate` from `balance_date` to today (balance × rate/100 × days / 365, 2 dp); `accrued_interest` = current − balance. Invested = `contributed` when set, else current (gain 0). xirr null. PPF maturity = 1 April of (the year the opening financial year ends + 15), e.g. opened 2026-06-01 → 2042-04-01; EPF and VPF have none. A PPF is never "matured": status is always active. Past maturity, `extended_until` = the end of the current 5-year block (maturity + 5 × n years, the first one after today); null before maturity.
- **NPS**: invested = `contributed`. Current = units × latest NAV (`nps_nav_latest`, 4 dp); with no NAV, current = contributed. `nav` and `nav_date` are in API items; `day_change` = units × (nav − previous stored NAV), as for MF. No XIRR; no status (always active).
- **Other**: current = `current_value` as entered (no price lookup; it changes only when the user edits it). With `invested_amount` set: invested = `invested_amount`, gain = current − invested, gain_pct = gain / invested × 100. Without it: invested = current, and `gain` and `gain_pct` are null (no gain is shown). xirr null. Always active (never matures). Totals skip a null gain, so those holdings add nothing to gain.
- gain = current − invested (payout FD: interest_received); gain_pct = gain / invested × 100. Group and dashboard totals SUM item gains (not current − invested; null gains are skipped). Aggregates also return `gain_base` = the invested of only those holdings that have a gain; the aggregate `gain_pct` = gain / `gain_base` × 100, so "Other" holdings without an invested amount don't dilute it. Outputs rounded to 2 dp.
- **Matured and sold holdings are closed**: they still appear in `items` (status `matured`, or `sold` after a full sale, §8b) but are excluded from every total (group totals, dashboard totals/allocation, holdings `summary`) and from `count`. `matured_count` reports how many were excluded. The holdings `summary` also has `closed_count` (matured plus sold); it is the same number as `matured_count` there.

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
- `GET /master/gold/rate?metal=gold|silver&purity=…&date=YYYY-MM-DD` (`metal` defaults to gold) → `{metal, purity, requested_date, rate_date, rate_per_gram}`: the IBJA rate on the date, or the last one up to 7 days before it. 422 for an unknown purity or a future date; 422 "Choose a purity" / "That purity isn't available for <metal>." when the purity doesn't fit the metal. 404 "Gold rate not available" / "Silver rate not available" with "No IBJA rate on or just before this date. Enter the amount yourself."
- `GET /master/nps?q=&limit=20` → active NPS schemes from `nps_master` with `nav` and `nav_date`. `q` ≥ 2 characters (else `[]`); every token must match scheme name or PFM name; ranked by trigram similarity on scheme name.
- `GET /master/nps/{scheme_id}` → one scheme (with nav and nav_date); 404 "Scheme not found".
- `GET /master/other/categories` → `string[]`: the signed-in user's Other categories, distinct ignoring case (each shown with the spelling of its newest holding), most used first (ties: most recently added first), at most 20. Soft-deleted holdings don't count. Feeds the category suggestions in the Other form.
- `GET /cron/nps` → runs the NPS NAV import (see Master data (NPS)) and returns its counts. Same bearer auth; Vercel `45 16 * * *` UTC. 502 "Couldn't fetch the NPS file" when the file can't be fetched.
- `GET /cron/amfi` → runs the AMFI import and returns counts. No X-API-Key; requires `Authorization: Bearer $CRON_SECRET`. Vercel Cron runs it daily at `30 16 * * *` UTC (22:00 IST).
- `GET /cron/securities` → runs the stock and bond master imports (see Master data). Same bearer auth; Vercel Cron `0 14 * * *` UTC. Returns `{stocks: {...}, bonds: {...}}`.
- `GET /cron/issuers` → runs the FD/RD issuer master import (§1) and returns its counts. Same bearer auth; Vercel Cron `0 3 * * 1` UTC (Mondays 08:30 IST, weekly). 502 "Couldn't fetch the issuer files" when both the Razorpay and DICGC sources fail.
- `GET /cron/gold` → runs the IBJA gold rate import (see Master data (gold rates)) and returns `{rate_date, session, rows_upserted}`. Same bearer auth; Vercel Cron `0 13 * * *` UTC. 502 "Couldn't fetch the gold rates" when the page can't be fetched or parsed.
- `GET|POST /assets/{type}`, `GET|PUT|DELETE /assets/{type}/{id}`; PUT is a full replace.
- **Soft delete** (migration 0025: nullable `deleted_at` on the nine holding tables; `other_holdings` has it from migration 0026). `DELETE /assets/{type}/{id}` sets `deleted_at`; every query (grids, portfolio, dashboard, net worth, details) hides deleted rows. MF transactions stay with their fund.
- `POST /assets/{type}/{id}/restore` clears `deleted_at` → `{message: "<Type> restored", description}`; 404 for a holding that isn't deleted or isn't yours.
- `GET /deleted` → the user's holdings deleted in the last 30 days, newest first: `[{type, type_label, id, name, deleted_at, purge_on, days_left}]`.
- `GET /cron/purge` → permanently deletes holdings (all users) deleted more than 30 days ago, and their MF transactions along with the fund; returns counts per table. Same bearer auth; Vercel Cron `0 20 * * *` UTC. Also `python -m app.jobs.purge_deleted` and the dev data refresh job `purge`.
- `GET /portfolio` → `{groups:[{type,label,items[],totals{invested,current_value,gain,gain_pct},count,matured_count}]}` (totals and count cover active holdings only) — always 10 groups in order fd, rd, stock, bond, mf, nps, gold, cash, pf, other. Items = record fields + `invested, current_value, gain, gain_pct, status` (`gain` and `gain_pct` are null for an Other holding without an invested amount), plus `maturity_date` (fd/rd/bond), `interest_received` (payout FD), and `nav` + `nav_date` (mf and nps: latest NAV, 4 dp, and its date; null when no NAV). Gold items carry `rate_per_gram` and `rate_date`. EPF & PPF items carry `accrued_interest`, `maturity_date` (PPF) and `extended_until` (PPF). The NAV lookups (MF and NPS) are one extra query each over held schemes only.
- `GET /dashboard` → `{total_invested,total_current,total_gain,gain_pct,by_type:[{type,label,count,matured_count,invested,current,gain,gain_pct,day_change,allocation_pct}],day_change,day_change_pct,day_change_as_of}`.
  - Each `by_type` row's `gain` and `gain_pct` are null when no active holding of that type has a gain. `day_change` is null when no active holding of that type has a real figure. Never 0 by default.
  - The 1-day change is `portfolio_day_change` in `api/app/services/valuation.py`, over active holdings only. MF and NPS use the item's own `day_change` (as of its `nav_date`); stocks use quantity × (price − prev_close) (as of `price_time`); gold and silver use weight × (latest rate − previous rate for the same metal and purity), only when a previous rate on an earlier date exists (as of the rate date). FD, RD, bonds, cash, EPF & PPF and Other contribute nothing.
  - `day_change_pct` is against the whole portfolio: change / (total current − change) × 100, null when that denominator is not positive. `day_change_as_of` is the latest date among the contributing figures.
  - All three are null, never 0, when no holding had a real figure. 0 is a real value (prices unchanged).
- `GET /search/index` → `{items:[{type,type_label,id,title,subtitle,terms:{ids,strong,weak},notes,current_value,gain_pct,status,updated_at}]}`, one flat item per holding (all ten types, active and matured), built from the same valued groups as `/portfolio`. Only the signed-in user's rows; soft-deleted holdings are excluded. The response carries `Cache-Control: private, no-store`. The browser does all matching and ranking.
  - `terms.ids`: tickers and codes (stock symbols, ISINs and BSE code from the linked master, bond ISIN and NSE symbol, MF scheme code and ISINs, NPS scheme id). `terms.strong`: issuer-like names (FD/RD bank and issuer short name, bond issuer, MF AMC, NPS fund manager). `terms.weak`: broker, platform, category and kind labels (bond type, MF category, gold metal, form and purity, cash and EPF & PPF kind, Other category). Terms repeating the title or an earlier term are dropped.
  - Master rows are read only for the masters the user's holdings link to, concurrently with the holdings query.
- `GET /holdings/{fd|rd|stock|bond|mf|nps|gold|cash|pf|other}` → server-side grid for one asset type. Values all holdings of that type, then filters, sorts and paginates in Python.
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
    - nps: `pfm_name*`, `tier`, `asset_class` (enum facets for tier and asset class). Sort keys: scheme_name, pfm_name, tier, asset_class, units, nav, contributed, current_value (default), gain, gain_pct, start_date. Search: scheme name, notes.
    - gold: `metal`, `form`, `purity` (enum facets); sort key `metal`
    - cash: `kind` (enum facet). Sort keys: name, kind, balance_date, current_value (default), interest_rate.
    - pf: `kind` (enum facet). Sort keys: name, kind, balance_date, current_value (default), interest_rate, maturity_date.
    - other: `category*` (grouped ignoring case; each shows the spelling of its newest holding). Sort keys: name, category, current_value (default), invested, gain, value_date; a null gain sorts last. Search: name, category.
    - (`*` = free-text values whose options come from the data.)
    - `status` on fd and rd: `active` | `matured`; bond: `active` | `matured` | `sold`; stock, mf, gold and other: `active` | `sold`. `closed` (matured plus sold) selects the Closed tab on every type that has one. Deposits are never sold.
  - Response: `{items (record + computed values), total, page, page_size: 10, page_count, summary{count, matured_count, invested, current_value, gain, gain_pct} for the whole type (unfiltered; active holdings only, count = active count), facets{<filter>: [{value, count}]}}`. Each facet counts rows matching every other filter. Enum facets list all values; text facets list values present for that type.
  - Item: record fields + `invested, current_value, gain, gain_pct, status`, plus `maturity_date` (fd/rd/bond), `interest_received` (payout FD), `nav` + `nav_date` (mf, nps), and `rate_per_gram` + `rate_date` (gold).
- `GET /holdings/{fd|rd|stock|bond|mf|nps|gold|cash|pf|other}/{id}` → `{item, master}` for the details page. `item` has the same shape as a grid row, plus `xirr`, `xirr_basis` and `xirr_transactions` for MF (§5; MF grid rows carry them too); `master` is the linked master read model (`app/schemas/market_master.py`), or null when the holding is not linked. 404 "Holding not found" / "It may have been deleted, or it belongs to another account."
- Auth: if `API_KEY` env is set, every route except `/api/health`, `/api/cron/amfi` (bearer `CRON_SECRET` instead) and OPTIONS needs header `X-API-Key` (401 otherwise).
- Sign-in: every route except `/api/health`, `/api/cron/*`, `/api/auth/*` and OPTIONS needs `Authorization: Bearer <access token>` (401 otherwise). Holdings are per user; see §7.

### Duplicate warnings

- `POST /assets/{type}` (create only; not edits, not CAS import, not SIP instalments) checks the user's active holdings of that type first. "Active" means not soft-deleted. The values compared are the ones the create would store, after master lookups (`scheme_code`, `master_id`, `issuer_id`). Code: `api/app/services/duplicates.py`.
- A match never blocks. The create returns **409** and the caller repeats it with `?confirm_duplicate=true` to add anyway. Without the flag and with no match, the create runs as usual.
- Match rules (same user and type; text is compared ignoring case and surrounding spaces):

| Type | Same… |
|---|---|
| FD | bank (the stored bank text), principal, start date |
| RD | bank, monthly instalment, start date |
| Stock | instrument (`master_id` when both holdings are linked, else name), quantity, buy date |
| Bond | instrument (`master_id` when both holdings are linked, else name), quantity, purchase date |
| MF | scheme (`scheme_code` when both are set, else scheme name), units, purchase date |
| NPS | scheme (`scheme_id`), start date |
| Gold & Silver | metal, form, purity, weight, purchase date |
| Cash & Savings | name, kind |
| EPF & PPF | kind, name |
| Other | name, category |

- 409 body: `{message: "This looks like a holding you already have", description, duplicates: [{id, name}]}`. The description is `<name> · <key facts> is already in your portfolio.`, or `... and N more are already in your portfolio.` when several match. The key facts are short, for example "₹1,00,000 from 1 Jan 2026" (FD), "10 shares bought 1 Jan 2026" (stock), "Savings account" (cash account kind), "EPF" (EPF & PPF kind). The matches are the existing holdings, oldest first.
- Web: the asset forms (`use-asset-form.ts`) open `DuplicateDialog` (`components/forms/duplicate-dialog.tsx`, rendered by `form-shell.tsx`) on a 409 with `duplicates`. It shows the API's message and description, the matching holdings as links to their details pages, and two buttons. Cancel closes it and leaves the form filled, nothing saved. "Add anyway" resubmits with `confirm_duplicate=true` and shows "Adding…" with a spinner; the create's own success or error toast then follows. The dialog also has pending state while the retry runs, and it doesn't close on Esc or outside click during the retry.
- `web/lib/duplicates.ts` reads the 409 (`readDuplicates`), adds the flag (`confirmDuplicatePath`) and builds the link (`duplicateHref`, `/portfolio/{type}/{id}`).
- SIP creates have their own duplicate check (§8a).

### Message contract (toasts render these verbatim)
- POST 201 → record + `message` ("Fixed deposit added" / "Recurring deposit added" / "Stock added" / "Bond added" / "Mutual fund added" / "Gold added" (or "Silver added" for silver) / "Cash & Savings added" / "EPF & PPF added" / "NPS added" / "Other added") + `description` (holding name: FD/RD bank[ · label], stock/bond name, MF scheme_name, gold or silver name, cash name, EPF & PPF name, NPS scheme name, Other name).
- PUT 200 → record + `message: "Changes saved"` + description.
- DELETE **200** → `{message: "<Type> deleted", description}` (gold rows: "Gold deleted" / "Silver deleted"; their 404 reads "Gold & Silver not found"). The web delete toast is a plain API message toast.
- Restore 200 → `{message: "<Type> restored", description}` (gold rows: "Gold restored" / "Silver restored").
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

- Pages: `/dashboard` Dashboard (top to bottom: the matured-holdings card when there is one, a hero row, then the holdings-by-type table).
  - Matured holdings to settle (`web/components/dashboard/unsettled-prompt.tsx`): shown at the top only when `unsettled.count` is above 0. Title "N matured holdings to settle · ₹X" ("matured holding" for one), then "This money left your totals. Tell us where it went." Rows: icon, name, "Matured {date}", amount and a Settle link to `/portfolio/{type}/{id}?settle=1` (opens the settle dialog). Three rows show; "Show All N" / "Show Less" appears beyond that. Data from `unsettled` in `/api/dashboard` (§8b).
  - Hero card (left, 2/3 wide on `lg`; stacked on smaller screens). Net worth at the top, then Invested, Gain / loss (signed amount and %) and 1-day change (signed amount and %, `text-gain` / `text-loss`, with an arrow). The 1-day change shows no as-of date. With no figure it shows "—" and no %. `day_change_as_of` is still returned by the API but not shown.
  - Growth over the selected range = change in (current − invested) from the first to the last point ("Growth (1Y) +…"). Shown only with 2 or more points.
  - Net worth chart inside the hero card: range toggle 1M / 6M / 1Y / All (default 1Y). The Y axis fits the data (padded, floored at 0). The gap between current value and invested is tinted: gain colour when the last point is at or above invested, loss colour otherwise. Dashed invested line.
  - Allocation donut beside the hero card (1/3 wide on `lg`). Slices are sorted by value. Top 5 types plus a "More" slice; "More" appears only when there are more than 6 types with value. Each slice has a fixed colour per type from `web/lib/asset-colors.ts` (neutral for "More"). Slices and legend rows link to `/portfolio/{type}`; "More" does not link. Legend percentages come from `allocation_pct`.
  - Holdings-by-type table (`web/components/dashboard/holdings-by-type.tsx`): rows grouped Deposits, Market-linked, Other (catalog order). A group subtotal row shows only when more than one group is visible. Columns: Asset type (with icon and a coloured allocation bar), Count, Invested, Current value, Gain (amount and %), 1-day, Allocation. Count, Invested and 1-day are hidden below `sm`. Each row links to `/portfolio/{type}` across the whole row. Types with no active and no matured holdings are hidden. A Total row closes the table.
  - `/portfolio` redirects to the first asset type you hold (first non-empty type in catalog order).
  - `/portfolio/{type}` shows compact pill tabs with an icon and a round green count badge (a pulsing placeholder while counts load). Deposits (FD, RD, Cash & Savings, EPF & PPF) come first, then a divider, then Market-linked (Stocks, Mutual Funds, NPS, Bonds, Gold & Silver), then a divider and Other. The order and groups come from `web/lib/asset-catalog.ts`, which also drives the Add menu, the `/add` gallery and the `/portfolio` redirect. The content fades in when the type changes; reduced motion is respected.
  - Each type has a summary strip (count, invested, current, gain) and an "Add FD"/"Add RD"/"Add stocks"/… button linking to `/add/{type}`.
  - Types with `statusTabs` (FD, RD, bond, stock, MF, gold and other) replace the "N active · M matured" text with an Active / Closed segmented control with counts (`components/portfolio/portfolio.tsx`). Active is the default (URL has no `status`; the request sends `status=active`); Closed sets `?status=closed`, resets to page 1, and hides the Invested/Current/Gain totals. Reset keeps the tab. An empty Closed tab shows "No closed {noun}". Closed sorts by Closed On, newest closed first by default. Its columns replace Current, Gain, Gain % and Status with Status (Matured · Settled, Matured · Not Settled or Sold), Closed On, Received and Realised Gain (§8b). The FD/RD/bond toolbar has no status filter (the Status column stays). The dashboard holdings-by-type table shows only the active count (no matured note).
  - Its own grid has type-specific columns and filters. Stocks include Price (latest price with day change %), Current/Gain/Gain %; a note under the stocks summary reads "Prices are the NSE/BSE closing price, updated nightly. Last updated <IST time>." Stocks without a price show current = invested. MF Current/Gain use the latest NAV where available (see §3). The MF grid has a sortable "XIRR" column after Gain % (signed %, `text-gain` / `text-loss`, "—" when null). It has a visible-by-default, non-sortable "NAV" column after Avg NAV: latest NAV with a muted "as of {date}" line, "—" when null.
  - The grid has debounced search, faceted filters, %-range and maturity-date range filters, Reset, and a Columns menu saved per type in localStorage `wt.portfolio.columns.{type}`.
  - Sortable headers; 10 rows per page; no totals row.
  - Row actions: eye (opens the details page `/portfolio/{type}/{id}`) and ⋯ Edit/Delete. Sell (active holdings of stock, bond, MF, gold and other) and Settle (matured deposits and bonds with no payout recorded) open their dialogs (§8b).
  - State lives in the URL. Breadcrumb reads `Portfolio › {type label}`.
- **Fresh data after changes.** Grids and the dashboard keep their data when the route is hidden and revisited (stale-while-revalidate). After a create, update, delete or CAS import made outside the grid, the grid, dashboard, tab counts and details page show their loading state on the next reveal instead of stale data (`web/lib/holdings-cache.ts`: version counters per type; `markHoldingsStale`, `holdingsVersion`, `anyHoldingsVersion`). In-grid edits and deletes refresh in place. `holdings-cache` subscribers refetch visible grids when a holding is deleted or restored.
- **Delete and Recently deleted.** The delete confirm dialog says: "It moves to Recently deleted and is permanently deleted after 30 days. Restore it from there if you need it." Restoring uses `restoreHolding` (`web/lib/restore-holding.ts`) and shows the API's "restored" toast. `/deleted` ("Recently deleted", `web/app/(app)/deleted/`, `web/components/deleted/recently-deleted.tsx`, linked at the bottom of the sidebar) lists `GET /api/deleted` with days left before permanent removal and a Restore action per row.
- **Type scale.** Root font is 110%. Body text is 13.5px; titles are 15.4px (`text-sm`); section labels are 11px uppercase; helper text is 13.2px (`text-xs`); grid filter buttons and popups are 12.5px. Inputs are `text-base` on phones (so iOS does not zoom on focus) and 13.5px from `md` up.
- **Global search** (top bar; `web/components/search/`, logic in `web/lib/search/`). Data comes from `GET /api/search/index`; everything is matched and ranked in the browser.
  - Trigger: from `md` up a "Search…" button with a ⌘K / Ctrl K hint, `clamp(10rem, 30cqw, 24rem)` wide, a container query on the top bar (`@container` on the header in `site-header.tsx`). Below `md` a search icon button.
  - Shortcuts: ⌘K / Ctrl+K opens and, when open, closes it; held-key repeats are ignored. It does not open while another dialog, alert dialog, sheet or menu is visible. `/` also opens it, but not when a modifier or a repeat is involved, when focus is in an input, textarea, select or editable text or inside a dialog, menu or listbox, or when a modal is visible (same rule as the `N` Add shortcut). Esc closes. ↑ ↓ move, Enter opens, ⌘/Ctrl+Enter opens in a new tab.
  - Ranking (`web/lib/search/rank.ts`): the query and the text are lower-cased, accent-stripped, with punctuation turned into spaces and "&" into "and", and the query is split into words; every word must match. Tiers, best first: 1 the whole query equals an id (ticker, code, ISIN); 2 equals the title; 3 is a prefix of the title (or of an alias, for pages and actions); 4 a word starts a title word; 5 an id starts with it; 6 the title contains it; 7 an issuer-like (strong) term contains it, 7.5 a weak term, subtitle or type label does; 8 a typo within one edit (two for words of 8+ letters; none under 4 letters) of a title word; 9 the notes contain it. A multi-word query ranks by its best word. Ties break by the sum of each word's own rank, then active before matured, then recently opened (the order when the palette opened), then higher current value, then title A to Z.
  - Results are grouped by asset type, groups ordered by their best match, 5 rows each with a "+N more" row that expands the group (and "Show fewer {type}" collapses it). A notes-only match shows a snippet of about 80 characters with the hit highlighted. "Go to" pages and "Actions" (Add {type}, Import CAS) matching the query follow the holdings, or come first when one of them ranks in a better tier than the best holding.
  - Empty query: "Recently opened" holdings, "Recent searches" (with a clear action) and "Quick links" (Dashboard, Add asset, Recently deleted). Recents are in localStorage `wt.search.recent` (max 8 each, case-insensitive duplicates removed; kept in memory when storage is blocked), are saved when a result is opened, and are cleared with the search index on logout (`clearSearchData`, called from the user menu).
  - Index: preloaded when the browser is idle after the top bar mounts (5 s timeout), kept in memory and shared. It is refetched when the palette opens if holdings changed since the last fetch (`web/lib/holdings-cache.ts`) or the data is older than 5 minutes; a refetch shows a small spinner and keeps the old data meanwhile.
  - States: first load shows placeholder rows (only under an entered query, or when there are recently opened holdings to resolve); no match shows "No results for “{query}”" with links to Recently deleted and Add asset; a failed first load shows the API's message and description with a Retry row (the old data is used when there is some). A screen-reader status announces the result count. Opening a result shows a pending state on its row until the page changes, then the palette closes; any route change closes it.
  - Mobile (below `md`): a full-screen top sheet that follows the visual viewport, with a clear button and Cancel, no key hints, and 16px input text. Opening pushes a history entry so Back closes the sheet; closing any other way pops it; opening a result replaces it. A hidden input is focused inside the tap so iOS raises the keyboard, then focus moves to the real input.
- **Net worth over time** (the chart in the dashboard hero card; `web/components/dashboard/net-worth-chart.tsx`). Data from `GET /api/networth/history?range=1m|6m|1y|all` (`api/app/routers/networth.py`, maths in `api/app/services/networth.py`), returning `{range, points:[{date, invested, current}], stocks_at_cost_before}`.
  - Rebuilt from current holdings. A holding counts from its start, purchase or buy date until it matures; matured holdings are excluded, as in the dashboard totals.
  - FD, RD and bond are valued with the `valuation.value_*` functions as of each date. MF = units × NAV on or before the date (`mf_nav_history`); no NAV → invested. NPS builds up linearly: from `start_date` to the holding's last update date (`updated_at`), invested and units are scaled by the elapsed fraction (0 at start, full from the update date); value = scaled units × NAV on or before the date (`nps_nav_history`); no NAV → contributed × fraction. Not counted before `start_date`.
  - If the CAS `mf_transactions` net to the holding's units, units come from the transactions and invested is the FIFO cost of the units held, counting from the first transaction. Otherwise units and invested are constant from the purchase date.
  - Stocks = quantity × stored close on or before the date (`stock_price_history`), else at cost. `stocks_at_cost_before` is the first point after the last point where any stock was at cost (null if none). Cash = `balance` counted from `balance_date` on (every date on or after it). EPF & PPF = balance plus simple interest to that date, counted from `balance_date` on.
  - Other counts from `acquired_on` when both `acquired_on` and `invested_amount` are set, else from `value_date`. Invested = `invested_amount` (the current value when none). Current = the current value from `value_date` on; between `acquired_on` and `value_date` it counts at cost (`invested_amount`).
  - Daily points for 1M, 6M and 1Y; weekly points back from today for All (from the earliest holding, max 10 years). The last point equals the `/api/dashboard` totals.
  - Chart: current value area, dashed invested line, range switch 1M / 6M / 1Y / All (default 1Y), Indian-format tooltip, compact axis (`formatINRCompact` in `web/lib/format.ts`). The web no longer shows a caption for `stocks_at_cost_before` (the API still returns it); "No history yet" when there are no points.
- Holding details page `/portfolio/{type}/{id}` (`web/app/(app)/portfolio/[type]/[id]/`): one shared layout for all ten types (`web/components/holding-detail/`), with per-type content from the `detail` block of each grid config (`web/components/portfolio/grid/configs/`). Data from `GET /api/holdings/{type}/{id}`. MF 4th card is "1-day change" (`day_change` ₹ with `day_change_pct` below); the latest NAV shows in the Holding section as "Current NAV". NPS has the same 1-day change card and Current NAV row.
  - Header: back link to the type's grid, type icon (`web/components/asset-type-icon.tsx`), name, sub-line, status badge, Edit and Delete.
  - KPI strip: Invested, Current value, Gain, and a type card: FD/RD/bond Maturity with days left; stock Price with day change; MF NAV with its as-of date. Cash hides the Gain card (`KpiStrip` `showGain` prop). EPF & PPF shows the Gain card only when a total deposited is set. Other shows it only when an amount invested is set, and its type card is "Value as of" (the date, with "Updated N days ago" below).
  - Tenure bar for FD, RD and bonds, and for PPF (EPF and VPF have none). A PPF past its 15 years shows the current extension block.
  - Sections: Holding, Instrument (only when linked to master data), Notes.
  - Edit opens the shared edit dialog (`web/components/portfolio/edit-dialog.tsx`, also used by the grid). Delete returns to the grid.
  - **XIRR (MF only).** The API returns `xirr` (annual %, 2 dp), `xirr_basis` (`transactions` | `purchase_date`) and `xirr_transactions` (number of stored transactions used). Actual/365; solved by Newton with a bisection fallback (`valuation.py`: `xirr`, `mf_xirr`). Null when it can't be computed.
    - Basis `transactions`: used when the stored `mf_transactions` (SPEC §8) have net units equal to the holding's units within 0.01. Cash flows: −amount on each purchase date, +amount on each redemption date, +current value on the NAV date (today when there is no NAV date).
    - Basis `purchase_date`: used otherwise, including all manual entries. Cash flows: −invested on the purchase date, +current value on the NAV date (or today).
    - Display: a row "XIRR" in the Holding section, right after "Purchase date", shows the signed % in `text-gain` / `text-loss`, with a muted note "from N transactions" (basis `transactions`) or "from purchase date" (basis `purchase_date`). It shows "—" when null. Shown for every holding, matured or not.
- `/add` (gallery of asset-type tiles grouped Deposits / Market-linked / Other, each with an "N held" count from `/api/dashboard`; registry in `web/lib/asset-catalog.ts`), `/add/{fd|rd|stock|bond|mf|nps|gold|cash|pf|other}` (form for that type; back link to `/add`; save → `/portfolio/{type}` (that type's tab), cancel → `/add`; unknown type → 404; legacy `/add?type=x` redirects to `/add/x`), `/login`, `/signup` (both without the sidebar).
- Browser calls only same-origin `/api/*`; `app/api/[...path]/route.ts` forwards to `API_URL` with `X-API-Key`.
- Sign-in is required everywhere, local dev included: `proxy.ts` redirects pages without the `wt_refresh` cookie to `/login?next=…`; cookies, refresh and the proxy rules are in §7. The top bar, right of the "Add asset" button, has an account menu (`web/components/user-menu.tsx`): a round avatar with the email's first letter (from `GET /api/me`) opens a dropdown with "Signed in as <email>" and "Log out".
- MF form (`components/forms/scheme-picker.tsx`): scheme picker is a server search over `/api/master/mf`, showing AMC · Plan · Option and the latest NAV. Picking sets the name and category (category stays editable). "Not listed? Enter manually" switches to free text.
- Gold form (`components/forms/gold-form.tsx`): fields Name, Purchase date, Metal (Gold or Silver, default Gold), Form, Purity, Weight (grams), Total invested. Metal, Form and Purity are themed selects. Purity options follow the metal; switching metal clears a purity that no longer fits. Total invested fills with weight × the IBJA rate for the metal and purity on the purchase date (`components/forms/use-gold-rate-autofill.ts`, which sends `metal`; the hint shows the rate and its date). It fills until the user types their own total, and stays editable. Errors show the API message as a muted hint.
- Gold grid and details (`components/portfolio/grid/configs/gold.tsx`): the rate column shows ₹/g with "IBJA, {date}"; the details page shows the rate used in the type card. A Metal column, filter and sort; the details page shows Metal. Facets are metal, form and purity. Gold has no status tabs.
- Cash form (`components/forms/cash-form.tsx`): fields Name | Account type, Balance | Balance as of (defaults to today), Interest rate, Notes. Account type is a themed select (Savings account, Current account, Cash in hand, Other). Interest rate is optional and uses the FD rate rules. Errors show the API message as a muted hint.
- Cash grid and details (`components/portfolio/grid/configs/cash.tsx`): no Gain or XIRR columns; the details page hides the Gain card. Empty state "No Cash Accounts yet". Facet is kind. Cash has no status tabs. The "Cash & Savings" tile is in the Deposits group of `/add` (Wallet icon).
- EPF & PPF form (`components/forms/pf-form.tsx`): fields Name | Account type (EPF, VPF, PPF), Current balance | Balance as of, Interest rate (%), Total deposited (optional), Opening date (PPF only; hidden for EPF and VPF). The account type pre-fills the interest rate (8.25% for EPF and VPF, 7.1% for PPF) until the user edits the rate. Errors show the API message as a muted hint.
- EPF & PPF grid and details (`components/portfolio/grid/configs/pf.tsx`): columns Name, Type, Balance, Accrued, Current value, Rate, Maturity ("Extended · till <date>" when extended). Facet is kind. PPF details show the tenure bar. The "EPF & PPF" tile is in the Deposits group of `/add`.
- NPS form (`components/forms/nps-form.tsx`): scheme picker (`nps-scheme-picker.tsx`, a server search over `/api/master/nps`; rows show PFM · tier · class and the latest NAV), then Units, Total contributed and Started on. Scheme is required (rule N1).
- NPS grid and details (`components/portfolio/grid/configs/nps.tsx`): scheme name with the PFM as a sub-line; columns Tier, Class, Units, NAV, Contributed, Value, Gain. Filters PFM, Tier and Class. The Instrument section shows scheme, PFM, tier and class. The "NPS" tile is in the Market-linked group of `/add`.
- Other form (`components/forms/other-form.tsx`): fields Name (placeholder "e.g. Bitcoin") | Category, Current value | Value as of (defaults to today), Amount invested (optional) | Purchase date (optional), Notes. Category (`components/forms/category-field.tsx`) is a themed combobox with free entry: a popover with a search box that lists the user's categories first (from `/api/master/other/categories`, "Loading your categories…" while they load; if that call fails the fixed list and free entry still work), then Crypto, Real estate, P2P lending, Art & collectibles, Unlisted shares, de-duplicated ignoring case. Typing text that isn't listed adds a `Use “<text>”` row; with no match and no text the list says "Type a category to use it". The trigger shows "Choose or type a category" until a value is set. Validation is O1–O4 (§2); the zod schema and the API use the same wording, including "Purchase date can't be after the value date" (shown on Purchase date).
- Other grid and details (`components/portfolio/grid/configs/other.tsx`): columns Name, Category, Value, Invested, Gain, As of; Invested and Gain show "—" when no amount invested was entered. Filter is Category (facet); search placeholder "Search other holdings…". The details page subtitle is the category; the Holding section lists Category, Current value, Value as of (with "N days ago", or "today"), Amount invested, Gain (with %), Purchase date; there is no Instrument section content. The "Other" tile (Shapes icon, hint "Crypto, property, anything else") is the only entry of the Other group in `web/lib/asset-catalog.ts`.
- **Forms lock while saving** (all ten types, add page and Edit dialog). `FormShell` (`components/forms/form-shell.tsx`) wraps its fields in a `<fieldset disabled>` and a `FormDisabledContext` (`components/forms/form-disabled.tsx`, read with `useFormDisabled`). Text, notes, select and date fields, the issuer, scheme and security pickers, the tenure controls and the category field read it: they are disabled and any open popover closes. The MF NAV and gold rate auto-fills and the picker searches pause while saving. `FormShell` also reports its saving state through `FormBusyContext` (`useReportBusy`; the CAS upload and import steps report too). The add page uses it to lock the MF "Import CAS" / "Manual entry" tabs, and the Edit dialog (`components/portfolio/edit-dialog.tsx`) ignores close requests, so it can't be dismissed mid-save. The submit button reads "Saving…" with a spinner; the CAS buttons show a spinner with "Reading…" and "Importing…".
- Stock form (`components/forms/stock-form.tsx`, picker from `components/forms/master-picker.tsx`): picker by default ("Search stocks and ETFs…"; rows show name, NSE/BSE symbols, ISIN, ETF badge). Picking sets name, symbol and the exchange default; changing the exchange re-derives the symbol. "Not listed? Enter manually" switches to free text; "Search the stock list instead" switches back.
- Bond form (`components/forms/bond-form.tsx`): picker ("Search bonds…"; rows show name, ISIN · type · coupon · maturity). Picking sets name, ISIN, issuer, bond type and maturity date (always), and fills purchase date (issue date, if not in the future) only when empty. All stay editable.
- Bond amounts: enter any two of Quantity, Purchase price per unit and Total invested; the third is calculated (price = total ÷ quantity, 2 dp; total = quantity × price; quantity = total ÷ price, rounded to a whole number). Pure helper `web/lib/holding-amounts.ts`, unit tests `web/lib/holding-amounts.test.ts` (`cd web && npm test`). Face value is not an input.
- MF amounts: the MF form has a "Total invested" field (`invested_amount`). Enter any two of Units, Average NAV and Total invested; the third is calculated (avg NAV 4 dp, units 3 dp, total 2 dp). The same helper (`web/lib/holding-amounts.ts`) is shared with the bond form. The NAV auto-fill counts as entering Average NAV, and it never overwrites a typed or computed value. Validation is rule 21.
- FD tenure: the FD form takes either Duration (years, months, days) or a Maturity date ("Duration / Maturity date" toggle). A maturity date is converted to years, months and days; the same §2 rules apply.
- FD and RD forms (`components/forms/fd-form.tsx`, `rd-form.tsx`): "Bank / issuer" picker (shared `components/forms/issuer-picker.tsx`, a server search over `/api/master/fd-issuer`; rows show the short name or name, the category, "DICGC insured" and "Merged into" when set). Picking sets `issuer_id` and copies the short name (or name) into Bank. "Not listed? Enter manually" switches to free text ("Search the bank list instead" switches back). New holdings open in picker mode; existing holdings without an issuer link open in manual mode. Editing loads the linked issuer from `/master/fd-issuer/{id}`, and falls back to the stored bank text if that fails.
- Edit dialog for stocks/bonds shows the linked security (fetched from `/master/stock/{id}` or `/master/bond/{id}`).
- MF Average NAV auto-fill (`components/forms/use-nav-autofill.ts`): once a scheme and purchase date are set, Average NAV fills from `/api/master/mf/{scheme_code}/nav` with the hint "NAV on {date} · AMFI". It stays editable and never overwrites a value the user typed or computed (see "MF amounts" above). Errors show the API message as a muted hint.
- Inputs: money/quantity/units use Indian digit grouping while typing (`components/forms/number-format.ts`); dates via themed DateField (Popover + Calendar, Monday first, month/year custom dropdowns, days outside allowed range disabled); payout FDs relabel Compounding → "Payout frequency" without Simple. Select menus open below their trigger, not over it.
- Toasts (sonner, themed): title = API `message`, description = API `description`.
- Theme: dark only, zinc palette, emerald primary, Geist Sans/Mono, root font-size 110%, sidebar 13.5rem.

### Landing page

- Public page at `/` for everyone (`web/app/(marketing)/page.tsx`), no sidebar and no sign-in. Signed-in users see a single "Open app" button (to `/dashboard`) in the nav and hero instead of "Log in" / "Get started"; the cookie check is in a Suspense-wrapped server component so the page stays static. `/welcome` redirects permanently to `/`; signed-in users opening `/login` or `/signup` go to `/dashboard`, and the default post-login destination is `/dashboard`. Paths ending in a file extension (files in `web/public`) pass through.
- Sections, top to bottom: nav, hero, sample-data dashboard preview, 6 features with a one-line privacy note below, footer (`web/components/landing/`).
- The dashboard preview uses made-up sample figures, not user data. The Holdings table hides its "Current" column below `sm`.
- Aurora background (`aurora.tsx`) is pure CSS. Reduced motion freezes it.

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
- **Holdings:** `fixed_deposits`, `recurring_deposits`, `stocks`, `bonds`, `mutual_funds`, `gold_holdings`, `cash_holdings`, `pf_holdings`, `other_holdings` each have `user_id` (NOT NULL, FK → users, ON DELETE CASCADE).
- Master tables (`mf_master`, `mf_nav_latest`, `mf_nav_history`, `stock_master`, `bond_master`, `gold_rate_latest`, `gold_rate_history`) stay global, with no `user_id`.

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

## 8. CAS import (mutual funds)

Code: `api/app/services/cas_import.py`, `api/app/routers/cas_import.py`, `api/app/schemas/cas_import.py`; web `web/components/forms/cas-import/`. On `/add/mf` the form has two tabs: "Import CAS" (first and default, reopened on every visit) and "Manual entry".

### Preview (`POST /api/import/cas/preview`, multipart `file` + optional `password`)

- The file must be a CAMS or KFintech CAS PDF, at most 4 MB, starting with `%PDF`. It is parsed in memory with `casparser` 1.4.1 (local, no network). The file and password are never stored or logged. The password is optional (unencrypted PDFs, e.g. some MF Central downloads, need none).
- MF Central "Detailed CAS" PDFs (which casparser cannot identify) are read by our own text parser, `api/app/services/mfcentral_cas.py`, as a fallback when casparser fails for a reason other than the password. Zero-unit rows (address updates, cancelled SIPs) are skipped. Invested = FIFO cost of the remaining units (outflows consume the oldest purchases first, proportionally to lot cost, 2 dp). If a scheme starts with a non-zero "Opening Unit Balance" its invested amount is unknown (cost empty) and the row's issue is "Statement starts after the first purchase. Download it from your first investment date."
- Errors (`{message, description}`):
  - 413 "File too large" / "Upload a CAS PDF smaller than 4 MB."
  - 422 "Couldn't read this statement" / "Upload a CAMS or KFintech CAS PDF." (not a PDF, or unreadable)
  - 400 "Wrong password" / "The CAS password is usually your PAN in capitals." (non-empty password rejected)
  - 400 "Password needed" / "This statement is password-protected. The password is usually your PAN in capitals." (password empty and the PDF is encrypted)
  - 422 "Depository statements aren't supported yet" / "Download a CAMS or KFintech CAS from MF Central." (NSDL or CDSL statement)
- Merge: schemes are grouped across folios by the matched `mf_master` scheme (AMFI code first, then ISIN; unmatched schemes group by ISIN or name). Schemes with zero closing units are hidden and counted in `hidden_zero`.
  - units = sum of closing units (3 dp); invested = sum of valuation cost (2 dp); avg NAV = invested ÷ units (4 dp).
  - purchase date = earliest PURCHASE, PURCHASE_SIP, SWITCH_IN or SWITCH_IN_MERGER after the running balance last reached zero; falls back to the valuation date when there is none.
  - name, AMC, plan, option and category come from `mf_master`; an unmatched scheme gets category `other` and its statement name.
- Each row has `existing` (the user's MF holdings in the same scheme: id, units, invested, avg NAV, purchase date), `importable` and `issue`. `importable` is true when the row passes the manual MF rules (§2, rule 21 included). Otherwise `issue` gives the first reason: "Not found in the AMFI scheme list", "Closing units are not positive", "The statement has no invested amount for this fund", "The statement has no purchase date for this fund", or the first rule message.
- Each row also carries `transactions`: the purchases and redemptions of all merged folios, sorted by date (`date`, `type` = `purchase` | `redemption`, `amount`, `units`). Zero-unit and zero-amount rows are dropped.
- Response: `statement_from`, `statement_to`, `rows`, `hidden_zero`.

### Review (web)

- One checkbox per row, ticked when `importable`. Each row shows a "New" badge, or "In portfolio" when `existing` is not empty.
- When exactly one holding matches the scheme, the row offers "Update existing" (default) or "Add as new".
- "Import N funds" submits the ticked rows.

### Commit (`POST /api/import/cas/commit`, JSON `rows`)

- Each row has `action`: `create` or `update` (update names the existing holding).
- Every row is validated like manual MF entry (§2). Validation is all-or-nothing: one failing row saves nothing.
  - 422 "Couldn't import — nothing was saved" / "<fund> — <reason>", where the reason is a field message (for example "Average NAV: …"), "Not found in the AMFI scheme list", or "The existing holding wasn't found".
- create: a new MF holding with platform empty, and its `transactions` saved to `mf_transactions` (table `mf_transactions`: one row per purchase or redemption, `txn_date`, `kind`, `amount`, `units`; FK to `mutual_funds`, ON DELETE CASCADE).
- update: replaces units, avg NAV, invested and purchase date, and replaces the holding's stored transactions with the row's `transactions`; platform and notes are kept.
- Manual entries never get transactions (no per-transaction entry).
- Transaction checks, in the same all-or-nothing 422 (`<fund name> — <reason>`):
  - "Transaction date can't be in the future"
  - "Transaction amount must be greater than 0"
  - "Transaction units must be greater than 0"
  - "Transactions: at most 2000 per fund"
- 200 → `message` "Imported N funds" ("Imported 1 fund" for one), `description` "X added, Y updated.", `created`, `updated`.

## 8a. Mutual fund SIPs

Code: `api/app/services/sip.py` (due dates, NAV, posting), `api/app/routers/sips.py`, `api/app/schemas/sip.py`, `api/app/models/mf_sip.py`; migration `0028` (`mf_sips`, `mf_sip_skips`, `mf_transactions.sip_id`). Tests: `api/tests/test_sip.py`, `test_sip_api.py`. Web: see "Web" below.

A SIP adds one purchase a month to a mutual fund holding. Each instalment is a `mf_transactions` row with `sip_id` set, so XIRR (§5) and net worth history (§5) count it like a CAS purchase.

### Fields and validation (`POST /api/sips`, `PUT /api/sips/{id}`)

- `scheme_code`: must be in `mf_master`, else 422 on `scheme_code` "Select a scheme from the list". An inactive scheme is 422 on `scheme_code` "This scheme is no longer active".
- `platform`: required, trimmed, at most 200 characters ("Required" / "Must be at most 200 characters").
- `amount`: at least ₹100 ("Must be at least ₹100"), at most 2 dp ("Up to 2 decimal places allowed"), at most ₹100 crore ("Must be at most ₹100 crore").
- `day_of_month`: a whole number ("Must be a whole number") from 1 to 28 ("Day must be between 1 and 28"). Days 29 to 31 are rejected, so every month has the day.
- `start_date`: on or after 1 Jan 1990 ("Date must be on or after 1 Jan 1990") and at most 366 days after today ("Date can be at most 1 year in the future").
- `end_date` (PUT only, optional): on or after 1 Jan 1990, and not before the SIP's start date ("End date must be on or after the start date").
- `include_past` (boolean, default false): see Due dates.
- `mutual_fund_id` (optional): a holding of yours that isn't deleted (else 404 "Holding not found" / "It may have been deleted, or it belongs to another account."), of the same scheme ("This holding is a different fund", on `mutual_fund_id`).

The web form uses the same wording (rule 3).

### Due dates and posting

- Due dates fall on `day_of_month` of each month. The first posted due date (`post_from`) is the first due date on or after the start date when `include_past` is true, or on or after today (IST) when it is false. Due dates after `end_date` are never posted.
- On create, the SIP posts its due instalments at once, and the message says how many were added.
- Skipped dates (`mf_sip_skips`) are never posted.
- Pause stops posting. Resume moves `post_from` to the next due date on or after today, so the paused months are never added later.
- **NAV rule.** An instalment uses the first NAV dated on or after its due date, so a weekend or holiday moves to the next trading day's NAV. The latest NAV is used only when its date is the due date itself; a past date never takes the latest NAV. When the stored history has no NAV for the due date, the scheme's history is fetched from mfapi.in, at most once every 6 hours. If no NAV is published yet, or the first NAV is more than 10 days after the due date (a history gap, unless the due date is older than the stored history), the SIP stops there and tries again on the next run. Nothing is posted out of order.
- **Amount and units.** Invested is the full amount. Units = amount × 0.99995 ÷ NAV (the 0.005% stamp duty is deducted first), rounded half up to 3 dp. The holding's avg NAV = invested ÷ units (4 dp).
- **Holding.** A SIP without a linked holding creates one at its first instalment: name from `mf_master` (at most 200 characters), the scheme code, the category from `mf_master`, the SIP's platform, and purchase date = the first instalment's NAV date. On create, the SIP links to `mutual_fund_id` when given. Otherwise it links to the holding of the same scheme and platform (platform compared ignoring case and spaces) when exactly one exists; with none or several, no holding is linked until the first instalment creates one.
- **Opening transaction.** When a SIP posts into an existing holding that has units but no `mf_transactions`, the first posting first writes one purchase for the holding's current units and invested, dated its purchase date. XIRR therefore stays on the transaction basis.
- **Deleted holdings.** A soft-deleted holding gets no instalments (the holding queries hide deleted rows). A SIP whose holding was purged for good posts nothing, so no new holding appears.
- **Idempotency.** `last_posted_on` (the due date of the last posted instalment) moves forward with each instalment, and `mf_transactions` has a unique (`sip_id`, `txn_date`). A re-run adds nothing new.
- **Nightly job.** `post_due_safely` runs at the end of `amfi.import_navall`, for every active SIP whose `post_from` is on or before today (IST). It never fails the import: errors are logged per SIP, and that SIP is skipped in the run. Both the prod AMFI cron (`/api/cron/amfi`) and the dev data refresh run it.
- **CAS import.** A CAS re-import (§8) replaces the holding's `mf_transactions`, so earlier instalments lose their `sip_id` and show as purchases. The SIP keeps running from `last_posted_on`, so no instalment is added twice.
- **Cancel.** Instalments already added stay in the holding. Deleting a SIP clears `sip_id` on its instalments and keeps them too.

### Endpoints (`/api/sips`, signed in, per user)

Each outcome returns `message` and `description`. A SIP read has: `id`, `mutual_fund_id` (null until a holding is linked), `scheme_code`, `fund_name`, `platform`, `amount`, `day_of_month`, `start_date`, `end_date`, `status` (`active` | `paused` | `stopped`), `next_date` (null unless active), `skipped_dates` (upcoming skipped dates, oldest first), `instalments_added`, `invested_via_sip`. A SIP that doesn't exist (including one already deleted) or belongs to another user is 404 "SIP not found" / "It may have been deleted already."

- `POST /api/sips` (201): the create body (fields above). `?confirm_duplicate=true` skips the duplicate check. Message "SIP started · N instalment(s) added" (singular for one), or "SIP started"; description `<fund> · ₹5,000 on the 5th of every month`.
  - **409 duplicate SIP** (unless `confirm_duplicate=true`): an active SIP of the same scheme, day and amount already exists. Body `{message: "This looks like a SIP you already have", description: "<scheme> · <schedule> is already running.", duplicates: [{id, name}]}`. The web shows it in the duplicate dialog.
- `GET /api/sips?mutual_fund_id=`: the user's SIPs (optionally one holding's), ordered active, then paused, then cancelled, by id.
- `PUT /api/sips/{id}`: amount, day of month and end date (null clears it). Message "SIP updated". It applies to future instalments only; posted instalments stay. A new day moves `post_from` to the next due date and drops upcoming skips on other days. A cancelled SIP is 409 "SIP is cancelled" / "A cancelled SIP can't be changed. Start a new one."
- `POST /api/sips/{id}/pause`: only an active SIP. Message "SIP paused". Otherwise 409 "SIP isn't running" / "Only a running SIP can be paused."
- `POST /api/sips/{id}/resume`: only a paused SIP. Message "SIP resumed". Otherwise 409 "SIP isn't paused" / "Only a paused SIP can be resumed."
- `POST /api/sips/{id}/stop`: cancels the SIP (the web's "Cancel"). Message "SIP cancelled", description "… instalments already added stay in your holding". Already cancelled: 409 "SIP is already cancelled" / "It has no more instalments to add."
- `POST /api/sips/{id}/skip`, body `{due_date?}` (default: the next instalment). Message "Instalment skipped", description `<fund> · 5 Dec 2026`. The date must be an upcoming instalment: today or later, on the SIP's day, not already posted, not after `end_date`. Otherwise 422 on `due_date` "Pick an upcoming instalment date". With no instalment left, 422 "There is no upcoming instalment to skip". The SIP must be active (409 "SIP isn't running" / "Only a running SIP has instalments to skip."). Already skipped: 409 "Instalment already skipped" / "<date> is already skipped."
- `DELETE /api/sips/{id}/skip/{due_date}`: undoes a skip while the date is still upcoming. Message "Skip removed", description `<fund> · 5 Dec 2026 will be added`. Not skipped: 404 "Skip not found" / "That instalment isn't skipped." A past date: 422 "Pick an upcoming instalment date".
- `DELETE /api/sips/{id}`: deletes the SIP and its skips. Message "SIP deleted", description "<fund> · instalments already added stay in your holding".
- `GET /api/holdings/mf/{id}/transactions?page=`: one fund's transactions, newest first, 10 a page (`page` is clamped to the last page). Items: `id`, `date`, `kind` (`purchase` | `redemption`), `amount`, `units`, `nav` (amount ÷ units; a SIP instalment's stamp duty is undone first, so this is the NAV used; null when units are 0), `sip` (true for a SIP instalment). Response: `items`, `total`, `page`, `page_size`, `page_count`. 404 when the fund isn't yours.
- **`sip` on MF holdings.** `GET /api/holdings/mf` rows and `GET /api/holdings/mf/{id}` carry `sip: {id, amount, day_of_month, status, next_date} | null`: the holding's active SIP, or its paused one when none is active; null otherwise (cancelled SIPs are hidden).

### Web

As built in `web/`; the code is the reference when the two differ.

- **Add page.** `/add/mf` has a third tab, "Start a SIP" (`components/forms/sip-form.tsx`, opened by `?tab=sip`), after "Import CAS" and "Manual entry". Fields: Fund (scheme picker), Platform, Monthly amount, SIP date (a day grid, 1–28, in `components/forms/day-of-month-field.tsx`; the trigger reads "5th of every month"), Start date. An "Add to" Select appears when the fund is already held: each of your holdings (platform · units) plus "A New Holding" (`components/forms/use-fund-holdings.ts` loads the holdings once for the picker). When the start date is in the past, a themed Yes/No asks whether to add the past instalments to the total ("Add the 10 past instalments (Jan to Oct 2026) to your total?"); the helper under it reads "Each is added to the holding at its own month's NAV." or "Only instalments from today onward are added."; the count and months come from `lib/sip.ts`. The submit button is "Start SIP", with pending state. Toasts and the 409 duplicate dialog come from the API (§4).
- **MF details page** (`/portfolio/mf/{id}`, `components/holding-detail/mf-sip-section.tsx`). SIP section: "₹5,000 on the 5th of every month · since Jan 2026", the next date, the status badge, and the same action menu as the SIPs table (`sip-actions.tsx`; see below). Transactions section (`mf-transactions.tsx`): a date tile, "SIP" / "Purchase" / "Redemption", amount, units and NAV. It shows 10 at a time with "Show 10 more", as Bond payouts do.
- **MF grid.** A small "SIP" badge on funds with an active SIP, "SIP paused" when the SIP is paused (`components/portfolio/grid/configs/mf.tsx`).
- **SIPs view** on `/portfolio/mf?view=sips`. A themed toggle "Holdings · SIPs" sits above the MF grid (`components/portfolio/portfolio.tsx`). The SIPs view is the SIPs table (`components/sips/sip-grid.tsx`), on the same grid parts as the holdings grids (search, faceted filter, sortable headers, paging of 10). Sorting, filtering and search run in the browser over `GET /api/sips` (`use-sips.ts`), which reloads after each action.
  - Summary line above the table: "Monthly SIPs" (total monthly amount of the active SIPs), "N active · next 5 Dec 2026", "Invested via SIPs", "Instalments added", and the "Start a SIP" button.
  - Search "Search SIPs…" (fund name or platform); a "Status" filter with Active, Paused, Cancelled.
  - Columns (`sip-grid-config.tsx`): Fund, Status (`sip-badge.tsx`: Active, Paused, Cancelled), Monthly amount, SIP date ("5th of every month"), Next instalment (or "Skipping 5 Dec" in amber while the next instalment is skipped), Instalments, Invested via SIP, and an actions menu.
  - Actions menu (`sip-actions.tsx`): Update SIP (dialog with monthly amount, SIP date and end date; `sip-edit-dialog.tsx`), Skip Next (confirm "Skip Instalment"), Undo Skip (shown in place of Skip Next once the next instalment is skipped), Pause SIP, Resume SIP, Cancel SIP (confirm "Keep SIP" / "Cancel SIP"; instalments already added stay) and Delete SIP (confirm; cancelled SIPs only). Per status: active → Update SIP, Skip Next or Undo Skip, Pause SIP, Cancel SIP; paused → Update SIP, Resume SIP, Cancel SIP; cancelled → Delete SIP.
  - Every action has a pending state ("Skipping…", "Cancelling…", "Deleting…"), and its toast text comes from the API. An empty state reads "No SIPs yet" and links to "Start a SIP".

## 8b. Closing holdings

Code: `api/app/services/exits.py` (the maths, and the only writers), `api/app/routers/exits.py`, `api/app/schemas/exits.py` (bodies, read models and the validation messages shared with the web), `api/app/models/holding_exit.py`; migration `0029` (`holding_exits`). Web: see "Web" below.

A closing is a sale (all or part of a holding) or a settlement (a matured deposit or bond paid out). Each writes one `holding_exits` row: `kind` (`sale` | `maturity`), date, quantity (sales), `amount` (money received, after charges), `cost`, `charges`, `destination` (`cash` | `none`), the cash account it touched, and `prev_state` (what undo needs).

### Sell (`POST /api/holdings/{stock|bond|mf|gold|other}/{id}/sell`)

- Quantity (shares, bonds, fund units or grams) can be part of the holding. Stock and bond quantities are whole numbers. Other is always sold whole; its sale value is sent as `amount` (before charges).
- `amount` = quantity × price − charges, 2 dp. For Other, `amount` = the sale value − charges.
- `cost` is what the sold part cost. A fund whose stored transactions match its units (within 0.01) uses FIFO over those transactions. Anything else uses the invested amount pro rata, never more than invested. A full sale takes all of the invested amount. Realised gain = amount − cost.
- A partial sale reduces the quantity and the invested amount by the cost, and recalculates a fund's average NAV.
- A full sale keeps the quantity and invested amount as they were and sets `closed_on` (status `sold`).
- A fund sale also writes a `redemption` transaction dated the sale date. A fund with no transactions yet gets an opening purchase for its current units first, so XIRR stays on transactions. A full sale of a fund stops its active and paused SIPs; the count comes back as `sips_cancelled`.
- The sale date can't be in the future or before the purchase date (stock buy date; bond, fund and gold purchase date; Other acquired date).
- A matured bond can't be sold, and a sold holding can't be sold again (409, see below).

### Settle (`POST /api/holdings/{fd|rd|bond}/{id}/settle`)

- Only a matured deposit or bond with no payout recorded. Both body fields default: `date` to the maturity date, and `amount` to what it pays at maturity (the same figure as Coming up, §9). The amount can be changed.
- The date can't be in the future or before the maturity date.
- One settlement per holding. A second one is 409, and so is a request that races it.

### Destinations

- `cash_existing` (`cash_id`): the account's balance goes up by the amount; its balance date becomes the later of its own and the exit date.
- `cash_new` (`cash_name`): a new savings account, with the amount as its balance, dated the exit date.
- `none` ("Spent Or Moved Elsewhere (Not Counted)"): nothing is added to any account.

Sell and settle take the same three choices. Money that went into an account can later be put into a holding with "Paid From" (§8c).

### Undo (`DELETE /api/exits/{exit_id}`)

- Only a holding's latest exit can be undone.
- A full sale clears `closed_on`. A partial sale adds the sold quantity and cost back. A fund's redemption transaction is deleted. SIPs that the sale stopped go back to paused; missed instalments are not added.
- A settlement puts the holding back to matured.
- Money added to an account is taken out again (the balance stops at 0, and its balance date is restored if nothing changed it since). An account the exit created is kept, and the message says so. Undo never deletes it.
- Undo is refused (409) while some of the money is reinvested, that is, paid into a holding that still exists (§8c).

### Endpoints

Each outcome returns `message` and `description`. Signed in, per user.

- `POST /api/holdings/{stock|bond|mf|gold|other}/{id}/sell` (201, `ExitResult`): body `{date, quantity?, price?, amount? (Other), charges (default 0), destination: {kind: cash_existing | cash_new | none, cash_id?, cash_name?}}`. Result: the exit fields plus `closed`, `remaining` (quantity left; null when closed or for Other), `cash_name` and `sips_cancelled`.
- `POST /api/holdings/{fd|rd|bond}/{id}/settle` (201, `ExitResult`): body `{date?, amount?, destination: {kind: cash_existing | cash_new | none, cash_id?, cash_name?}}`.
- `GET /api/holdings/{type}/{id}/exits`: the holding's exits, newest first (`id`, `kind`, `date`, `quantity`, `amount`, `cost`, `charges`, `destination`, `cash_holding_id`, `cash_added`, `new_holding_id`, `new_asset_type`, `realised_gain`, `reinvested`, `left_in_account`).
- `DELETE /api/exits/{exit_id}`: undo (above). Returns `message` and `description`.
- `GET /api/master/stock/{id}/close?date=`: the stock's close on the date or up to 7 days before it, as `{price, price_date, source: history | latest}`. It pre-fills the sell price. 404 "Price not available" / "No close for this stock on or just before this date. Enter the price yourself."
- Grid and details items carry `exit` (the latest exit, or null), `settled`, and `maturity_amount` (matured, unsettled deposits and bonds only). `GET /api/dashboard` carries `unsettled`: `{count, amount, items: [{type, id, name, maturity_date, amount}]}`, the matured FD, RD and bonds that are not sold and have no payout recorded, oldest maturity first.

### Messages

Validation (422 on the field named; the web forms use the same wording):

- Date: "Date can't be in the future"; "Date can't be before the purchase date" (sell); "Date can't be before the maturity date" (settle); "Date must be on or after 1 Jan 1990".
- Quantity: "Required"; "Must be greater than 0"; "Must be a whole number" (stock, bond); "Can't sell more than you hold"; "Up to 3 decimal places allowed"; "Must be at most 1 crore".
- Price: "Required"; "Must be greater than 0"; "Up to 4 decimal places allowed"; "Must be at most ₹100 crore".
- Amount (Other): "Required"; "Must be greater than 0"; "Up to 2 decimal places allowed"; "Must be at most ₹100 crore".
- Charges: "Can't be negative"; "Charges must be less than the sale value"; "Up to 2 decimal places allowed"; "Must be at most ₹100 crore".
- Destination: "Choose where the money went" (unknown kind); "Choose one of your accounts" (`cash_id` not yours); "Required" and "Must be at most 200 characters" (`cash_name`).

Conflicts (409):

- "Already sold" / "This holding has been sold. Undo the sale first if it was a mistake." (sell a sold holding)
- "This bond has matured" / "Record where the money went with Settle instead of selling." (sell a matured bond)
- "Already sold" / "This bond was sold before it matured. Undo the sale first." (settle a sold bond)
- "Not matured yet" / "<name> matures on 5 Jan 2027." (settle before maturity)
- "Already settled" / "Undo the settlement first if you need to change it." (settle twice, or two at once)
- "Undo the latest one first" / "A later sale of this holding was recorded after this one." (undo an older exit)
- "Holding not found" / "It was deleted. Restore it from Recently deleted, then undo." (undo a deleted holding)

Not found (404):

- "Holding not found" / "It may have been deleted, or it belongs to another account."
- "Can't be sold" (sell on a type that can't be sold: fd, rd, NPS, cash, EPF & PPF); "Can't be settled" (settle on any other type). Both use the same description.
- "Record not found" (undo an unknown exit), with the same description.
- "Price not available" (see the close endpoint).

Success:

- Sell: "Stock sold", "Bond sold", "Fund sold", "Gold sold" or "Silver sold", "Holding sold" (Other); a part sale reads "Part of stock sold" (and so on). Description: `<name> · <quantity> sold for <amount>`, then "gain ₹X" or "loss ₹X" when there is a cost and the gain is not zero, then "added to <account>", then "SIP cancelled" or "SIPs cancelled".
- Settle: "Maturity recorded"; description `<name> · ₹X received` or `<name> · ₹X added to <account>`.
- Undo: "Sale undone" or "Settlement undone". Description: "<name> is back in your portfolio.", then "₹X was taken out of <account>." when money was taken out, then "The account <name> was kept; delete it yourself if you don't want it.", then "Its SIP was left paused; resume it if you still want it." when that applies.

### Web

As built in `web/`; the code is the reference when the two differ.

- **Sell dialog** (`components/exits/sell-dialog.tsx`; the grid's row menu "Sell" and the details page's Sell button, for active holdings of the five sellable types). Title "Sell {name}". Fields: Date; the quantity field (label "Quantity" for stock, "Bonds" for bond, "Units" for MF, "Weight (g)" for gold; "Sell All" fills it, and the button then reads "Selling All · Clear"); the price ("Price per share", "Price per bond", "NAV per unit", "Rate per gram"; a stock's price is pre-filled from its close on the sale date); for Other, "Amount" (the sale value); Charges (hint "Brokerage, taxes or fees paid on the sale"); "Where Did The Money Land?" (see the destination field below). Submit "Sell", pending "Selling…".
- **Settle dialog** (`components/exits/settle-dialog.tsx`; the details page's Settle button or banner, and the dashboard card's link, which opens it at once). Title "Settle {name}", description "Matured on <date>". Fields: "Amount received" (pre-filled with the amount it pays at maturity); "Date received"; "Where Did The Money Land?". Submit "Settle", pending "Settling…".
- **Destination field** (`components/exits/destination-field.tsx`, used by both dialogs). Label "Where Did The Money Land?". Options, in order: each cash account ("Name · ₹balance"), "A New Savings Account" (its name pre-filled from the bank, e.g. "HDFC Bank Savings"), "Spent Or Moved Elsewhere (Not Counted)". The effect line under it reads "Name: ₹old → ₹new" for an account, "Adds ₹X to your net worth" for a new account, and "This ₹X won't be added to your net worth." for none. Below that, the info line "Investing this money later? Pick this account under 'Paid From' when you add the holding, so it isn't counted twice." (§8c).
- **Success step** (`components/exits/reinvest.tsx`, `ExitSuccess`). After a sell or settle that put money in an account, the dialog shows "₹X is now in <account>." with "Reinvested some of it?" and buttons "+ Mutual Fund", "+ FD", "+ Stock", "+ Bond", "+ Gold", "More…" and "Done". Each button opens that type's add form paid from the account (§8c); "More…" opens the type gallery without a prefill.
- **Details page** (`components/holding-detail/holding-detail.tsx`, `exits-section.tsx`). A matured deposit or bond with no payout recorded shows a banner: "Matured on <date> · ₹X paid out. Where did the money go?" with a Settle button. Below the sections, "Sales and settlements" lists the exits, newest first: "Sold 40 shares" (or "Sold" for Other, "Settled" for a settlement); "Into <account>" or "Spent or moved elsewhere"; "Gain ₹X" or "Loss ₹X"; and the money line (§8c, "reinvested · still in"). A "Reinvest" menu (same buttons as the success step) shows on each exit that still has money in an account. Only the latest one has Undo: a dialog asks "Undo this sale?" or "Undo this settlement?" with "Keep It" and "Undo" (pending "Undoing…").
- **Grid row menu** (`components/portfolio/grid/row-actions.tsx`): "Sell" on active holdings of the sellable types; "Settle" on matured deposits and bonds with no payout recorded.
- **Closed tab** (`components/portfolio/grid/closed-columns.tsx`, `lib/closed.ts`). Status: "Matured · Settled", "Matured · Not Settled" (outlined, so it stands out) or "Sold". Closed On. Received: the exit amount, else the maturity amount. Realised Gain: amount − cost, with a "+" on a gain.
- **Dashboard card** (`components/dashboard/unsettled-prompt.tsx`): see §5.
- **Coming up** (§9): matured rows show their amount and a "Not Settled" badge until the payout is recorded.

## 8c. Paid from

Code: `api/app/services/fundings.py` (the maths, and the only writer of `holding_fundings`), `api/app/schemas/fundings.py` (the `paid_from` body and its messages), `api/app/models/holding_funding.py`, `api/app/routers/assets.py` (create, delete, restore). Migration `0030` (`holding_fundings`). Web: see "Web" below.

Every Add form (`/add/{type}`) has an optional "Paid From" field. It applies to all ten types, including MF lump sums, stocks, bonds, FDs, RDs, gold and silver. Choose an account (e.g. "HDFC Savings") and the amount comes out of that balance. Leave it as "Outside Money (New Money)" and nothing changes. Net worth stays correct with no double counting: the money is already in the account, so it is counted once, as the holding.

### Flow

- Settle or Sell money lands in a cash account (§8b).
- Investing it later uses Paid From: the add form takes that account.
- After a settle or sell that put money in an account, the success step offers Reinvest buttons (+ Mutual Fund, + FD, + Stock, + Bond, + Gold) and "More…", which goes through the type gallery. The details page's Reinvest menu does the same.
- The prefill (type, amount left in the account, exit date, account and exit) is passed through sessionStorage (key `wt.reinvest`), not the URL. The add form takes it once, only for that type, and clears it.

### Data

`holding_fundings` (migration `0030`): one row per holding created with a paid-from account.

- `user_id`, `asset_type` (`fd` | `rd` | `stock` | `bond` | `mf` | `nps` | `gold` | `cash` | `pf` | `other`), `holding_id` (no foreign key: it points at the table named by `asset_type`).
- `cash_holding_id` (the account; set null when the account is deleted for good), `amount` (2 dp), `funded_on` (the holding's start, purchase or acquired date, or today when blank), `from_exit_id` (the sale or settlement the money came from, if any; set null when that exit is deleted).
- `prev_balance_date` (the account's balance date before the debit, kept for the record), `refunded_at` (null while the funding is active).

### Amount taken per type

The amount is what the holding costs, rounded to 2 dp. None is taken when it is 0.

- FD: principal.
- RD: monthly instalment × the instalments paid so far (due on or before today and before maturity, counted as the valuation counts them). With no instalment paid yet, the RD is saved and nothing is taken.
- Stock: quantity × average buy price.
- Bond, MF, Gold & Silver: invested amount.
- NPS: contributed.
- Cash & Savings: the opening balance.
- EPF & PPF: contributed, or the balance when contributed is blank.
- Other: amount invested (required, see Validation).

### Cash effect

- Create: the account's balance goes down by the amount. Its balance date becomes the later of its own and `funded_on`.
- Delete (soft): the balance goes back up by the amount, and `refunded_at` is set. The balance date is not changed.
- Restore: the amount is taken out again and `refunded_at` is cleared. The balance date is not changed.
- Edit: never changes the funding (see below).
- Purge (§8b, `services/purge.py`): the funding rows of a purged holding are removed. No money moves, as the refund was made at delete.
- When the account is deleted, delete and restore move no money. The line on the holding then reads "a deleted account".

### Validation

Validation (422 on the field named; the web forms use the same wording and check it live):

- `paid_from.cash_id`: "Choose one of your accounts" (not one of your active Cash & Savings accounts).
- `paid_from.from_exit_id`: "Choose one of your accounts" (not one of your exits).
- `paid_from.cash_id`: "More than this account's balance" (the amount is more than the balance).
- `paid_from.cash_id`: "Enter the amount invested to pay it from an account" (the holding has no amount invested, such as Other without one).

The `paid_from` check runs before the duplicate check (§4). A 422 wins even when the holding also matches a duplicate. A 409 duplicate rolls back, so nothing is debited; "Add anyway" repeats the create with `confirm_duplicate=true` and debits then.

### Edit

`PUT /api/assets/{type}/{id}` takes no `paid_from` and never changes the funding. Changing the holding's amount does not move money. The Edit dialog shows the funding as a read-only line: "Paid from HDFC Savings · ₹50,000" (or "Paid from a deleted account · ₹50,000").

### Restore

Restoring a holding takes its refunded fundings out of their accounts again. When an account has too little, the restore is 409 and nothing changes: "Not enough in <account>" / "Update its balance, then restore."

### Exits

- `reinvested` on each exit (and on its `exit` summary on holding items): the money of that exit put into holdings that still exist (active fundings with `from_exit_id` set to it). Deleting such a holding lowers it again.
- `left_in_account`: `cash_added` less `reinvested`, never below 0; null when the money went into no account.
- Undo is refused while `reinvested` is above 0: 409 "Some of this money was reinvested" / "Delete the holdings paid from it first, then undo." (§8b, Undo).
- The details page line: "₹50,000 reinvested · ₹57,186 still in HDFC Savings", or "₹1,07,186 in HDFC Savings" when none was reinvested.

### API fields

- `POST /api/assets/{type}` takes an optional `paid_from`: `{cash_id, from_exit_id?}`. Omitted or null means outside money.
- Holding items (grid and details) carry `paid_from`: `{cash_holding_id, cash_name, amount, date}` for an active funding, else null. `date` is `funded_on`.
- The create result's description appends the money taken: `<name> · ₹50,000 taken from HDFC Savings`.
- Exits carry `reinvested` and `left_in_account` (§8b, Endpoints).

### Web

As built in `web/`; the code is the reference when the two differ.

- **Paid From field** (`components/forms/paid-from-field.tsx`; logic in `lib/paid-from.ts`). Label "Paid From". Options: "Outside Money (New Money)", then each account ("Name · ₹balance"). While accounts load: "Loading Accounts…". The helper line under it: "Bought with money already in one of your accounts? Pick it so it isn't counted twice." With an account chosen, the effect line reads "HDFC Savings: ₹2,25,000 → ₹1,75,000". Edit dialog: no select, only the read-only line.
- **Reinvest note** (above the add form when prefilled, `components/exits/reinvest.tsx`, `lib/reinvest.ts`): "Reinvesting ₹1,07,186 from HDFC Savings." The amount field takes the amount; for RD and stock there is no single amount field, so the hint "₹50,000 to invest" shows instead.
- **Gallery note** (`web/components/add/asset-gallery.tsx`): while a reinvest prefill is pending, the /add type gallery shows "Reinvesting ₹1,07,186 from HDFC Savings. Pick what you bought."
- **Success step**, **Reinvest menu** and **money line**: as in §8b, Web.
- **Cash & Savings details page** (`components/holding-detail/holding-detail.tsx`): the info line "Use this account as 'Paid From' when you add a holding bought with this money."
- **Destination info line** on the sell and settle dialogs: as in §8b, Web.

### Out of scope

- "Buy more" for an existing holding (adding money to a holding already held).
- SIP instalments taking money from an account. A SIP's instalments are not paid from a cash account.

## 9. Analytics (slice 1: Overview)

`GET /api/analytics/overview` (`routers/analytics.py`; maths in `services/analytics.py`, shapes in `schemas/analytics.py`) returns `as_of` plus six sections computed from the user's valued holdings and loaded masters. Only active holdings count; matured ones are excluded from every figure except the already-matured and data-health lists. Money is 2 dp; percents are of the section's own total.

### Sections

- **allocation**: `including_retirement` and `excluding_retirement` views (`total`, `classes` → `types` → `holdings`, each with `value` and `percent`; classes with no value are left out), plus `retirement_value` and `retirement_percent`. Retirement = EPF, VPF, PPF and NPS Tier I (a missing tier counts as Tier I).
- **concentration**: `top_holdings` (10, by value), `others` (`{count, value, percent}`: the holdings after the top 10, computed from unrounded values; zeros when there are 10 or fewer), `rollups` (stock company, MF AMC, FD/RD bank, bond issuer, NPS PFM; bar percent is of that group's total; ETF bars are `passive`) and `flags`.
- **liquidity**: six buckets, always listed, adding up to the active total.
- **coming_up**: `next_30_days`, `next_90_days`, `next_180_days`, `next_12_months` windows and `already_matured`.
- **bank_safety**: DICGC cover per bank.
- **data_health**: `at_cost`, `stale_balances`, `matured_open`, `latest` price dates.

### Classification (equity, debt, hybrid, gold, cash, other)

- Stock: equity. An ETF is classified by its name (below), default equity.
- MF: by the linked scheme's AMFI category: equity scheme or ELSS → equity; arbitrage → debt; hybrid scheme → hybrid; debt or income/debt scheme → debt; gold or silver → gold; overseas → equity; index fund or ETF category → by name, default equity; domestic fund of funds and solution-oriented → by name, default hybrid. With no linked scheme or no rule: by name, then the holding's own category (equity, ELSS and index → equity; debt and liquid → debt; hybrid → hybrid), else other.
- Bond: debt; an SGB (holding or master `bond_type`) is gold. FD, RD, EPF, VPF, PPF: debt. Gold & Silver: gold. Cash: cash. Other: other.
- NPS: by the scheme's asset class: E → equity; C, G and A → debt. Themed, lifecycle, composite, tax saver and similar schemes have none, so by name: a whole word EQUITY → equity; a debt name → debt; otherwise hybrid.
- By name (`classify_by_name`, whole tokens, in order): gold or silver → gold; liquid, overnight, arbitrage, gilt, SDL, bond, Bharat Bond, target maturity, money market, G-sec, T-bill, debt, income → debt (so a "Nifty SDL" or target-maturity index fund is debt, not equity); NIFTY or SENSEX → equity; otherwise the default.

### Liquidity buckets

Instant: cash. 1-3 days: stocks and ETFs, MF other than ELSS, digital gold and silver, NPS Tier II. Breakable: FD and RD. Illiquid: bonds, physical gold and silver. Locked: EPF, VPF, PPF, NPS Tier I, and the ELSS part inside its 3-year lock. Not classified: Other. Retirement money is included.

ELSS funds are split per lot: purchases and redemptions from stored transactions, FIFO redemptions, then the value is split by remaining units still inside the lock-in (a unit bought exactly 3 years ago is free; the locked part is rounded to 2 dp and the free part is the rest). Without usable lots the whole fund follows its purchase date; with no date it counts as locked.

### Coming up

Active FDs, RDs, bonds and PPFs maturing strictly after today. Windows end at today + 30, 90 and 180 days and today + 1 calendar year, all inclusive; each longer window includes the shorter ones. Rows are sorted by date, type, id and carry `amount`, `rate`, `days_left` and `approximate`.

- Amount: cumulative FD, value on maturity; payout FD, its principal; RD, value on maturity with every instalment paid (approximate); bond, face value × quantity (SGB: its current value; a bond with no face value: invested amount grown at the yield; both approximate); PPF, balance plus interest to maturity (approximate, later contributions are unknown). Perpetual bonds have no date and are skipped.
- `already_matured` lists holdings whose status is matured (count and rows). They are never counted in a window total. Each row has `amount` (what it paid at maturity) and `settled`.

### Bank safety

FD and RD only (cash isn't linked to a bank). Exposure per deposit is its current value; a payout FD counts its principal only. A deposit rolls up to a bank by this chain: the issuer link followed through `merged_into_id` to the surviving issuer; else the issuer whose name or short name equals the entered bank (trimmed, case-insensitive, following merges); else the entered name, grouped case-insensitively. Each bank row is rounded to 2 dp and totals are sums of rows.

- Cover is `limit` = ₹5,00,000 per bank (DICGC). Status from the surviving issuer: `insured` (insured = min(total, 5,00,000), excess = the rest); `not_insured` (insured 0, excess = total; NBFCs and HFCs always, other banks when the DICGC flag is false); `sovereign` (Post Office: no cover figure, excess 0); `unknown` (flag NULL or no linked issuer: insured and excess null, never counted as uninsured).
- Badges: not_dicgc, cooperative, small_finance, post_office. Banks sort by excess, then total, largest first. `total_deposits` = insured + uninsured_excess + unknown_amount + sovereign_amount.
- Caveat: the cover is per depositor per bank per capacity. Joint accounts and other capacities are insured separately, so this can over-warn (the card's info tooltip says so).

### Concentration

The web shows Top 10 (holdings by value, % of total; the remainder appears as an "Everything else" segment and row when `others.count` > 0) or one rollup chosen in a Select. Flags (strictly over): a non-ETF stock company above 10% of the equity class total (retirement money included), and an AMC above 30% of the MF total. ETFs and passive funds never get the single-stock flag. Each flag carries its `threshold`.

### Data health

- `at_cost`: active stocks, MFs, NPS and gold with no price, NAV or rate (valued at cost).
- `stale_balances`: active cash, EPF/PPF and Other whose balance or value date is more than 6 calendar months old (exactly 6 months is not stale); items carry `as_of`.
- `matured_open`: holdings whose status is matured.
- `latest`: newest stock price, MF NAV, NPS NAV and gold rate dates among held items (null when none).

### Growth (`GET /api/analytics/growth`)

Splits the change in net worth into new money and growth. Pure maths in `services/analytics_growth.py`; the daily points come from the net worth history (`load_history`, range `1y`), so valuation is not duplicated. Response: `as_of`, `stocks_at_cost_before` (passed through from the history), `periods` and `months`; money and percents 2 dp.

- `periods` (in order): `this_month` ("This month"), `last_month` ("Last month"), `fy` ("FY to date"), `ytd` ("This year"), `1y` ("1 year"). Each has `start_date`, `end_date`, `start_value`, `end_value`, `new_money`, `growth`, `change`, `growth_pct`.
- Start dates: this month = last day of the previous month; last month = last day of the month before last; FY = 31 March of the current Indian FY (1 April start; in Jan–Mar, 31 March of the previous calendar year); YTD = 31 Dec of the previous year; 1 year = today minus 1 year. End = today, except last month = last day of last month.
- A date's value is the history point on or before it (`current` for value, `invested` for new money). With no such point (holdings began later) the start values are 0.
- `new_money` = invested(end) − invested(start); `change` = current(end) − current(start); `growth` = `change` − `new_money`; `growth_pct` = growth ÷ start value × 100, null when the start value is 0.
- `months`: the last 12 calendar months, oldest first, each `month` (YYYY-MM), `start_value`, `end_value`, `new_money`, `growth`, `change`, by the same rules (start = last day of the previous month, end = last day of the month, today for the current month).
### Page (`/analytics`, sidebar "Analytics")

- Top to bottom: the data-health strip, then Allocation beside Liquidity, Bank safety beside Coming up (two columns from `lg`, stacked below), then Concentration full width, then the footer line "Prices as of <newest `latest` date>" (right-aligned; hidden when there is none).
- Data-health strip: an amber strip shown only when `at_cost` or `stale_balances` has items ("Some figures may be off: N valued at cost · N stale balances"); a Details toggle lists the items, each linking to its holding. `matured_open` is not shown there (already-matured lives on the Coming up card).
- Allocation: donut (shared `components/charts/donut.tsx`, also used by the dashboard allocation card) with class rows that expand to asset types and holdings (links to the holding). An "Include retirement" switch swaps the view; off shows a line with the excluded retirement amount and percent. Fixed colour per class.
- Liquidity: headline = instant + 1-3 days amount, subline "available within 3 days · N% of your portfolio", a segmented bar and bucket rows (zero buckets hidden).
- Bank safety: headline in red when over the cover ("₹X over the ₹5L cover"), muted when only unknown cover, green when all covered; bank rows expand to their deposits (links).
- Coming up: themed Select for the window (Next 30 / 90 / 180 days, Next 1 year; default 90 days), total, rows with a date block, type, rate, "~ approximate" and amount (links), and an expandable "N already matured" list. A matured row shows its amount and, until its payout is recorded, a "Not Settled" badge (§8b).
- Hover is linked: hovering a donut slice, bar segment or legend row dims the others. No native controls.
- States: skeleton while loading, API-sourced error with Retry, and an empty state ("No holdings yet" with an "Add a holding" button) when there are no active holdings. The page reloads after holding changes (`holdings-cache`).

### Returns (`GET /api/analytics/returns`)

`routers/analytics_returns.py`; maths in `services/analytics_returns.py`, shapes in `schemas/analytics_returns.py`. Same active holdings and asset classes as the Overview. Returns `as_of`, `overall`, `by_class`, `by_type` (groups: `invested`, `current`, `gain` = current − invested, `return_pct`, `annualised`, `basis`, `since` = earliest cash flow, `holdings`), `best` and `worst`, `rates` and `excluded`. Money and percents are 2 dp.

- Cash flows per holding: MF, the stored CAS transactions when their net units match the holding (basis `transactions`), else the invested amount on the purchase date (`purchase_date`); FD, bond, stock and gold, −invested on the start/purchase date and +current value today (`purchase_date`); RD, −instalment on each paid instalment date up to today and +current value today (`instalments`); Other, only with both an invested amount and an acquired date. A group's basis is `mixed` when its holdings differ. A group's XIRR runs over the concatenated flows of its holdings.
- Interest paid out: a payout FD (interest paid out, valued at principal) also gets a positive flow for each interest payout on its payout date (the schedule `value_fd` uses for `interest_received`; a payout falling today joins today's flow). Only payout FDs report `interest_received`; bonds are valued by accrual, so they have no payout flows. Holding and group `gain` is the valuation `gain` (includes interest received), so it matches the Portfolio grid; the under-one-year return is gain / invested. The benchmark replay sells index units for these payouts like any other inflow before today.
- Under one year: when the earliest flow is less than 365 days old, `return_pct` is the absolute return gain / invested × 100 and `annualised` is false; otherwise it is the XIRR % (null when the solver can't converge).
- `best` / `worst`: up to 5 holdings each (`type`, `id`, `name`, `return_pct`, `gain`), highest first / lowest first; a holding never appears in both. Only holdings whose earliest cash flow is on or before today minus 6 calendar months are ranked, by their yearly return = the XIRR of the holding's own flows (annualised even for 6–12 month holdings); `return_pct` is that yearly return. Holdings whose XIRR can't be computed are skipped. This does not change the `return_pct` of holdings in groups or the under-one-year absolute rule above.
- `excluded` (counts): `at_cost` (stock, MF or gold with no price, NAV or rate), `no_flows` (cash, EPF/VPF/PPF, NPS; also a holding with no usable start date), `other_without_invested`.
- `rates`: PF rows show their interest rate (`basis` `interest_rate`); NPS rows show the scheme NAV CAGR since the start date (`nav_cagr`), null when the NAV history has no NAV within 7 days on or before the start date or the holding is under a year old.
- `benchmark` (null when the index fund's NAV history can't be had, or there are no holdings with flows): `label` ("Nifty 50 index fund"), `scheme_name`, `nav_date` (latest NAV used), `equity` and `overall` (`your_pct`, `benchmark_pct`, `annualised`), `fd_rate`, `inflation_pct`, `inflation_period`. Maths in `services/analytics_benchmark.py`.
  - Index: UTI Nifty 50 Index Fund, direct growth (`BENCHMARK_SCHEME_CODE` 120716). Its NAV history comes from the existing store (`nav_history.resolve_nav`, mfapi.in): fetched on request only on first use. The nightly AMFI import (`refresh_benchmark_history`) refetches it when its sync is older than 24 h, so the latest NAV is added each night. The NAV on or before each date is used.
  - Replay (public-market equivalent): the group's own flows (equity class for `equity`, all included holdings for `overall`); each outflow buys index units, each inflow dated before today sells units, and the remaining units x latest NAV is the terminal value. `benchmark_pct` is the XIRR of those flows (absolute return when the earliest flow is under 365 days old, then `annualised` is false); `your_pct` is the group's `return_pct`. A flow dated before the first available NAV makes that group's `benchmark_pct` null.
  - `fd_rate`: principal-weighted average rate of the active FDs; null without FDs.
  - Inflation: `api/data/cpi_india.csv` (India annual average CPI-Combined inflation per calendar year, hand-maintained). `inflation_pct` is the compounded annual average from the overall group's `since` year (or the first year in the file) to the latest year; `inflation_period` is that span ("2021–2025"); both null when there is no overlap.

### Interest & TDS (`GET /api/analytics/tax?fy=<start year>`)

`routers/analytics_tax.py`; maths in `services/analytics_tax.py` (the module docstring has the rules), shapes in `schemas/analytics_tax.py`. `fy` is the start year of the financial year: the current or the previous one (`available_fys`, current first); any other value is 422. Omitted = current. Money 2 dp.

- FY window: 1 Apr to 31 Mar. Interest is counted as accrued in (a, b], a = 31 Mar before. Current year: `to_date` runs to today and `projected` to 31 Mar, assuming no new deposits. Previous year: both are the full year.
- FD and RD, active or matured (a deposit that matured this year still earned its interest this year). Cumulative FD: growth at b minus growth at a, each clipped to [start, maturity]. Payout FD: payouts dated in the window. RD: value at b minus value at a minus instalments paid in the window.
- Savings accounts (kind savings with a rate): balance x rate x days / 365, an estimate that assumes the balance stands all year. Shown as `savings`, not a payer, so no TDS estimate.
- Bond coupons, counted on payment dates. Regular (monthly, quarterly, half_yearly, yearly): face value x quantity x rate / 100 / payments a year, on dates stepped back from maturity every 12 / n months, counted when after the purchase date. `on_maturity`: simple interest (compounding bonds: yearly) from issue date to maturity, paid on the maturity date and counted only when that date is in the window. SGB: half-yearly at the master coupon rate (2.5% if none) on master issue price x quantity (grams). A bond with no master, no coupon rate, `none`, `irregular` or unknown frequency (non-SGB), or missing dates is not counted; it is counted in `excluded.bonds`.
- Tax-free: PPF, EPF and VPF interest = balance x rate x days after the balance date in the window (zero before it); tax-free bond coupons (`tax_free` bond type). Neither is a payer.
- Payers: FD and RD by resolved bank, bond coupons by issuer (`kind` `bond`). Thresholds: banks (incl. co-operative and post office) 50,000; NBFC and HFC 10,000. `tds_rule`: `threshold` for FD and RD payers (the thresholds above); `every_payment` for a bond payer with any corporate or other bond (10% TDS on every coupon, no threshold, `threshold` null); `none` for a bond payer whose bonds are all government securities or SGBs (no TDS, `threshold` null). Interest exactly at a threshold does not count.
- TDS estimate: a `threshold` payer whose projected interest is over its threshold gets 10% of its whole year's projected interest (`crosses`, `tds_estimate`); otherwise 0. An `every_payment` payer gets 10% of each coupon dated in the year (`tds_estimate` is the sum of its coupon TDS; `crosses` is false, as there is no threshold); `none` gets 0. A payer's `tds_estimate` is split across its holdings (`holdings[].tds_estimate`): FD and RD by share of projected interest, a bond holding by its own coupon TDS. Assumes PAN is given.
- By class (`by_class`): one row per asset class with interest, in the order `fd`, `rd`, `bond`, `savings` (savings only when there are savings accounts). Each row: `type`, `label`, `interest_to_date`, `interest_projected`, `tds_estimate` (savings 0), `holdings_count` (savings: accounts). Classes with no holdings are left out.
- Response: `fy` (label, e.g. 2026-27), `fy_start`, `fy_end`, `as_of`, `is_current`, `available_fys` (`start_year`, `label`, `is_current`), `payers` (`key`, `name`, `kind` bank | company | bond, `tds_rule` threshold | every_payment | none, `threshold` (null unless the rule is `threshold`), `interest_to_date`, `interest_projected`, `crosses`, `tds_estimate`, `holdings`: `id`, `type` fd | rd | bond, `name`, `interest_to_date`, `interest_projected`, `tds_estimate`), `by_class` (`type` fd | rd | bond | savings, `label`, `interest_to_date`, `interest_projected`, `tds_estimate`, `holdings_count`), `totals` (payers only: `interest_to_date`, `interest_projected`, `tds_estimate`), `savings` (`interest_estimate`, `accounts`; null when none), `taxable` (`interest_to_date`, `interest_projected`: payers + savings), `tax_free` (`interest_to_date`, `interest_projected`, `items`: `kind` ppf | epf | vpf | tax_free_bond, `id`, `name`, `interest_to_date`, `interest_projected`), `excluded` (`bonds`).
- Web (`/analytics/interest`, tab "Interest & TDS"), in this order: Bond payouts (all bonds, see below); a toolbar with the financial year Select and the slab Select; a summary strip; the interest-by-type card; footnotes.
  - Summary strip, three figures side by side: Taxable interest (so far this year, or full year for a past one), TDS deducted (by banks and issuers) and Left to pay, or Refund due when TDS is more. Left to pay = tax at the slab (taxable interest x slab x 1.04; 4% cess, surcharge ignored; whole rupees) minus the TDS; it reads "Pick your slab" until a slab is chosen. A line under the figures adds the tax-free interest (PPF, EPF, VPF and tax-free bonds) when there is any.
  - The slab (0% to 30%, themed Select) is stored only in the browser under `wt.analytics.taxSlab` and never sent to the server.
  - Interest-by-type card ("Interest this year, by type", or "Interest in FY 2025–26, by type" for a past year): one row per asset class (Fixed Deposits, Recurring Deposits, Bonds, Savings) with its total, a bar and a TDS pill in plain words (`classTdsPill` in `web/lib/tax.ts`): "₹X TDS · over the limit at N banks" (or "payers"), "No TDS · under ₹50,000 per bank", "No TDS · each payer under its limit", "₹X TDS · 10% of each coupon" or "No TDS on these bonds" for bonds, and "Banks don't cut TDS on savings". This year, the bar shows interest received (gain colour) against still to come; a past year shows each class's share. A row with payers opens to its payers (banks, companies, bond issuers); a payer opens to its holdings with their TDS; a bond holding opens to its payout dates (Paid or Upcoming).
  - Footnotes: the savings estimate sentence when there are savings accounts; "N bonds without coupon details aren't included" only when `excluded.bonds` > 0.
  - A thin indeterminate bar along the top of a card shows while another financial year loads.

### Bond payouts (`GET /api/analytics/bond-schedule?id=<bond id>`)

`routers/analytics_tax.py`; schedule maths in `services/bond_schedule.py` (rules in its docstring), shapes in `schemas/analytics_tax.py`. An estimate: frequency and rate come from the linked bond_master; coupon dates are stepped back from the maturity date every 12 / n months (clamped to the month end), counted only when after the purchase date. `on_maturity` bonds get one coupon on the maturity date (simple interest, or yearly compounding for compounding bonds). The redemption is paid on the maturity date: face value x quantity, or for an SGB the master issue price x grams (`estimated_value` true).

- TDS: 10% of every coupon for corporate and other bonds (`tds_rate` 10); government securities, SGBs and tax-free bonds have none (`tds_rate` 0). The redemption never has TDS. `net` = `gross` − `tds`.
- Planned sale (`services/bond_schedule.py` `is_planned_sale`): when the holding's `maturity_date` is earlier than the bond's own `maturity_date` in `bond_master` (e.g. a platform that auto-sells the bond), that date is an exit date, not a maturity. Coupon dates still step back from the master's maturity date (the bond's own calendar); only those after the purchase date and on or before the exit date count. The closing payment is a `sale` (not a redemption) of face value x quantity (SGB: issue price x grams) on the exit date, `estimated_value` true, no TDS, and not interest. A bond that pays all its interest on maturity and is sold early gets no coupon, only the sale. Without a master maturity date, or when the master date is not later than the holding's, nothing changes.
- Response: `as_of`, `bonds` (`id`, `name`, `issuer`, `bond_type`, `coupon_rate`, `frequency` (SGB: half_yearly), `face_value`, `quantity`, `purchase_date`, `maturity_date` (the holding's date: the exit date for a planned sale), `planned_sale` (bool), `bond_maturity_date` (the master's maturity, null when none), `tds_rate`, `estimated` true, `payments` (`date`, `kind` coupon | redemption | sale, `gross`, `tds`, `net`, `fy`, `paid` (dated on or before today), `estimated_value` on redemptions and sales), `next_payment` (first unpaid payment; null when none), `by_fy` (oldest first: `fy`, `coupons` (count), `gross`, `tds`, `net`)), `excluded` (count of bonds with no workable schedule; not listed).
- `id` limits the response to one bond; an id that is not one of the user's active bonds is 404 ("Bond not found").
- Web: "Bond payouts" card (`components/analytics/bond-schedule.tsx`) on the Interest & TDS tab (all bonds, with an All Bonds or one-bond Select when there is more than one) and on the bond details page (that bond only).
  - Headline: next payout (net, with days and date).
  - Monthly stacked columns: each month's net, with its TDS on top; a ◆ marker on a month with a repayment of principal. A tap or hover on a month shows a floating card beside it: the month, its status (Paid, Upcoming or Part paid), the amount, coupon and TDS, and up to three items ("+N more").
  - By financial year, rows of Coupons, TDS and You get (net), with a share bar. A row expands to its payouts (date, bond name when several, Paid or Upcoming, gross, TDS, net; a repayment reads "◆ Repayment of principal"), 10 at a time with "Show more" and "Show less".
  - Planned sale: the sale month gets a hollow ◇ marker (the legend reads "◇ Planned sale"); its rows read "Planned sale · estimated" with "≈" amounts. The single-bond view adds a note: "You plan to sell on …; the bond matures …".
  - Info popover: "Estimated dates".

### Money coming in (`GET /api/analytics/inflows?months=12|24`)

Route in `routers/analytics_tax.py`; events in `services/cashflows.py`, shapes in `schemas/analytics_cashflows.py`. Dated inflow events of active holdings only, from today on, each split into `interest` and `principal`, gross (before any TDS):

- Bonds: each coupon (`coupon`, interest) and the redemption (`redemption`, principal), from the bond schedule. A planned sale (see Bond payouts) gives its closing `sale` (principal, estimated) in place of the redemption. A bond with no workable schedule gives nothing.
- Payout FD: each interest payout (`interest_payout`, interest) and the principal at maturity (`maturity`, principal).
- Cumulative FD: one `maturity` event, principal = the principal, interest = value at maturity − principal.
- RD: one `maturity` event, principal = instalments paid, interest = value at maturity − instalments paid.
- Stocks, MF, NPS, gold, cash, PF and Other give nothing.

- Response: `as_of`, `months` (`months` calendar months starting with the current one; empty months included; `month` "YYYY-MM", `interest`, `principal`, `items` sorted by date: `date`, `type` fd | rd | bond, `id`, `name`, `kind`, `interest`, `principal`), `totals` (`interest`, `principal`), `types` (the types that have items, in fd, rd, bond order). Any `months` other than 12 or 24 is 422 ("Choose 12 or 24 months.").
- Web: "Money coming in" card on the Overview page (`components/analytics/inflows-card.tsx`), full width below the Bank safety | Coming up row, with its own fetch. Headline total with interest and principal; a column per month (interest in the gain colour, principal in the money colour); a tap or hover on a month lists its items. Themed Selects: Asset type ("All Types" or a type present in the period), Amount shown ("Interest + Principal" or "Interest Only"), Period ("Next 12 Months" or "Next 24 Months"). A planned sale is listed as "Planned sale (est.)" and counted as principal. 24 months use narrow columns with a label every other month.

# Analytics for Wealth Tracker: use cases, screens, ranking
> Backlog (2026-11-02): analytics research. Next up after soft delete, the "Other" asset, global search and mobile/PWA. Tax figures are as of FY 2025-26; check them before building.

Written 2026-11-02 from a read of AGENTS.md, docs/SPEC.md, docs/STATUS.md, `api/app/models/`, `api/app/services/valuation.py`, `api/app/services/networth.py`, `api/app/routers/portfolio.py` and `web/components/dashboard/`. Nothing in the repo was changed.

Tax figures below are the rules as I know them for FY 2025-26 / tax year 2026-27. **Verify every rate and threshold before you build.** India has changed capital-gains and TDS rules almost every year since 2023, and the Income-tax Act, 2025 (in force from 1 April 2026) renumbers the sections ("80C" etc. get new numbers and "tax year" replaces "previous year"). Keep every rate, threshold and holding period in one dated config table, never in code.

---

## 0. What the data can and cannot support today

### Stored per holding (exists)

| Type | Useful for analytics | Notable gaps |
|---|---|---|
| FD | bank text, `issuer_id` → `fd_issuer_master` (category, `dicgc_insured`, `merged_into_id`, `accepts_deposits`), principal, rate, start, tenure → maturity, compounding, payout vs cumulative | No "tax-saver 5-yr FD" flag (80C). No holder or joint-holder. No senior-citizen flag. |
| RD | bank / `issuer_id`, instalment, rate, start, tenure | Instalments assumed paid on time. |
| Stock | quantity, avg price, **one** buy_date per row, `master_id` → `stock_master` (ISIN, kind stock/etf, NSE/BSE symbols, `bse_group`), latest close + prev close, `stock_price_history` (12 months, month-end backfill, then nightly) | **No sector, no market-cap class, no index membership.** No sells, dividends, splits or bonuses. Many lots of one stock = many rows (or one averaged row). |
| Bond | issuer, `bond_type` (government/corporate/tax_free/sgb/other), invested, purchase date, YTM, maturity, `master_id` → `bond_master` (coupon, `interest_frequency`, rating + agency, ownership PSU/non-PSU, perpetual, issue price) | Value is YTM accrual, **including SGBs** (see pitfall below). No coupon receipts. No listed/unlisted flag (needed for tax). |
| MF | `scheme_code` → `mf_master` (**AMC, `amfi_category` e.g. "Equity Scheme - Large Cap Fund", plan direct/regular, option growth/IDCW**), units, invested, purchase date, latest NAV + prev NAV, `mf_nav_history` (10 y, on demand), **`mf_transactions` (CAS imports only: every purchase and redemption with date, amount, units)** | Manual entries: one lot, no transactions. No expense ratio (TER). No portfolio look-through. No stamp duty/exit load. |
| NPS | `scheme_id` → `nps_master` (PFM, **tier I/II, asset class E/C/G/A**), units, contributed total, start date, NAV history back to 2009 | **No per-year contributions** (80CCD(1B) needs them). No employer vs own split. |
| Gold & Silver | metal, form (jewellery/coin/bar/digital), purity, grams, purchase date, invested; IBJA rate latest + history (from 27 Oct 2026 only) | Older purchases have no rate history. Making charges excluded by design. |
| Cash | name, kind (savings/current/cash/other), balance, optional rate, balance date | **No bank link** (`issuer_id`), so savings balances can't join DICGC exposure. |
| EPF/VPF/PPF | kind, balance, balance date, rate, optional contributed, PPF opened_on → maturity and extension block | **No per-year deposits** (PPF ₹1.5L cap, 80C). No employee/employer split. |

### Global market data (exists)
AMFI NAVs (latest + 10-y history on demand), NSE/BSE closes (latest + held-stock history), NPS NAVs (history to 2009), IBJA gold/silver (from 27 Oct 2026), bond master with ratings, issuer master with DICGC flag.

### Missing everywhere (name these when deciding)
1. **Realised history.** A sale is a delete: the row, its cost and its gain vanish. Only CAS-imported MF redemptions survive (in `mf_transactions`). This limits realised gains, true lifetime returns and FY reports.
2. **Benchmarks.** No Nifty/Sensex series, no CPI, no FD reference rate. (A Nifty 50 index-fund NAV from `mf_nav_history` is a free, good-enough TRI proxy; see §2.)
3. **Classification.** Stock sector / market cap; ETF underlying (gold vs equity vs liquid ETF); MF "index" category hides whether it's equity or debt.
4. **User profile.** Tax regime (old/new), age / senior-citizen status, monthly expenses, target allocation, goals, retirement age.
5. **Contributions by year** for PPF, EPF/VPF, NPS (tax deductions, PPF cap).
6. **Liabilities.** Loans aren't tracked, so "net worth" is really gross assets.

### Pitfalls the analytics will inherit (handle up front)
- **Matured holdings are excluded from totals** but still exist; analytics must follow the same rule or say why not.
- **"At cost" fallbacks**: stocks without a price, manual MFs without a scheme code, NPS without a NAV, gold without a rate all show current = invested (0% return). Performance views must flag or exclude them, or they'll drag XIRR towards zero.
- **SGB is valued at YTM accrual**, not gold price. An SGB bought at ₹4,800/g is now worth roughly the IBJA 999 rate per gram. For allocation it is gold, and for value it should be grams × IBJA 999 (RBI redeems at the 3-day IBJA average). This is a real valuation bug to raise separately; analytics will expose it.
- **NPS builds up linearly** in net-worth history (one contributed total). Its XIRR from a single start date is wrong; don't show one.
- **Single-purchase-date XIRR understates SIPs** (the team already pulled MF XIRR once for this). Any portfolio XIRR must say which basis it uses.
- **Hybrid MFs**: equity share varies 10–80% by sub-category; "Arbitrage" is debt-like in risk but taxed as equity.
- **Stock splits and bonuses** aren't tracked; quantity × new price is wrong until the user edits the row.
- **Merged banks** (e.g. Syndicate → Canara): DICGC limit applies to the surviving bank. `merged_into_id` exists for this.

---

## 1. Use cases: what the user actually asks, and how often

Persona: salaried or self-employed Indian, 28–60, holds a mix of FDs in 2–5 banks, a few MFs via SIP (CAS-imported), some direct stocks, EPF through the employer, a PPF, maybe NPS, family gold, a couple of savings accounts. Files ITR once a year, may or may not use a CA.

### A. Daily / "glance" (opens the app with coffee)
| Question | Frequency | Notes |
|---|---|---|
| "How much did I make or lose today?" | Daily on market days | Stocks (prev close), MF and NPS (prev NAV). Habit-forming; cheap. |
| "Which holdings moved the most?" | Daily / weekly | Top gainers and losers by ₹ and %. |
| "Is my data up to date?" | Weekly | Price dates, stale cash/PF balances. |

### B. Monthly check-in (after salary, SIPs, statement emails)
| Question | Frequency |
|---|---|
| "How much did my net worth grow this month, and how much of that was my own saving vs market?" | Monthly |
| "Where is my money? Equity vs debt vs gold vs cash." | Monthly |
| "Am I too concentrated? One stock, one fund house, one bank?" | Monthly / quarterly |
| "Is anything maturing soon? Where do I put it?" | Monthly; urgent in the week before a maturity |
| "How much of this can I actually get my hands on if I need it?" | Rarely, but critical when it happens (job loss, medical) |
| "Do I have enough emergency money?" | Quarterly |
| "Is my money in banks safe? Am I above the ₹5 lakh DICGC cover anywhere?" | Quarterly, and after any bank-news scare (PMC, Yes Bank, co-op bank moratoria) |

### C. Quarterly / half-yearly review
| Question | Frequency |
|---|---|
| "How did I really do? What's my return (XIRR) overall and per asset class?" | Quarterly |
| "Did I beat an FD? Inflation? Nifty?" | Quarterly / yearly |
| "Should I rebalance? How far am I from my target mix?" | Half-yearly, or after a big market move |
| "Am I holding junk? Regular plans, IDCW options, 4 large-cap funds, tiny positions?" | Half-yearly |
| "What interest is coming in, and when?" (retirees, FD-ladder users) | Monthly for retirees; quarterly otherwise |
| "What's the credit quality of my bonds and FDs (NBFC, co-op, SFB)?" | Quarterly |

### D. Tax season (Jan–Mar for planning, Jun–Jul for filing)
| Question | Frequency |
|---|---|
| "How much 80C have I used? Do I need to invest more before 31 March?" (old regime only) | Jan–Mar, yearly |
| "How much interest will I have to declare this year? Will the bank cut TDS? Should I file 15G/15H?" | April (15G/H) and Jan–Mar |
| "If I sell now, is the gain short- or long-term? How much tax?" | Before every sale |
| "Can I book ₹1.25 lakh of equity LTCG tax-free this year (gain harvesting)?" | Feb–Mar yearly |
| "Which ELSS units are out of their 3-year lock-in?" | Before redeeming |
| "What were my realised capital gains this FY?" (ITR Schedule CG) | Jun–Jul yearly |
| "Did I hit the PPF ₹1.5L cap / ₹500 minimum this FY?" | March |

### E. Life decisions (event-driven)
| Question | Trigger |
|---|---|
| "Am I on track for retirement / child's education / house down-payment?" | Birthdays, new child, job change |
| "What will my PPF / EPF / NPS be worth at maturity or at 60?" | Yearly, job change |
| "If I need ₹10 lakh in 6 months, what do I break first and what does it cost me?" | House purchase, medical, wedding |
| "What should I do with this maturing FD: renew, ladder, debt fund?" | Each maturity |
| "Should I move this regular-plan fund to direct?" | Once, then on new purchases |
| "Can I partially withdraw from PPF yet? When does my PPF extension block end?" | Event-driven |

### F. Annual
| Question | Frequency |
|---|---|
| "Year in review: what did I add, what did I earn, what were the best and worst holdings?" | April (FY) or January |
| "How has my allocation changed over the year?" | Yearly |

---

## 2. Analytics screens and widgets (full catalogue)

Legend: **Data** = exists / derivable / missing (named). **Effort** S ≤ 1 builder task, M = 2–3 tasks (endpoint + UI + maybe a table), L = new data source, rules engine or many tasks. **Value** high / medium / low for this user.

Reuse note: `routers/portfolio.py` `load_groups()` already returns every valued holding with invested/current/gain/maturity. Most "regrouping" analytics are one new endpoint that calls `load_groups()`, adds one query per type for master fields (MF `amc`/`amfi_category`/`plan`/`option`; FD/RD issuer `category`/`dicgc_insured`/`merged_into_id`; NPS `tier`/`asset_class`; bond `rating`/`coupon_rate`/`interest_frequency`), and computes in a pure service module (pattern of `services/networth.py`, testable without a DB). Web: a new `/analytics` route in the `(app)` group, a sidebar entry (`web/components/app-sidebar.tsx`), and charts via the existing shadcn chart (`components/ui/chart.tsx`).

---

### 2.1 Asset-class allocation (economic exposure)
- **Answers:** "Where is my money? Am I too heavy in equity / FDs?"
- **Shows:** donut or stacked bar of Equity / Debt & fixed income / Gold & silver / Cash / (optional) International equity; toggle "include retirement money (EPF, PPF, NPS Tier I)" since many users mentally separate it. Drill-down table: class → asset type → holdings, with ₹ and %.
- **Mapping:** stocks → equity (ETFs by name: GOLD/SILVER → gold, LIQUID/BEES liquid → cash-like, NIFTY/SENSEX → equity, BHARATBOND/GILT/SDL → debt); MF by `amfi_category` (Equity, ELSS → equity; Debt, Liquid, Money Market → debt; "Index Funds"/ETFs by name, as stocks; Hybrid: either a "Hybrid" bucket or split by sub-category typical mix, e.g. Aggressive 75/25, Balanced Advantage 50/50, Conservative 25/75, Arbitrage → debt-like; FoF Overseas → international; Gold ETF/FoF → gold); NPS by `asset_class` (E equity, C and G debt, A alternative/debt); bonds → debt **except SGB → gold**; FD/RD/PF → debt; cash → cash; gold holdings → gold.
- **Data:** derivable (all fields exist). ETF/index classification needs a small name-rule seed.
- **India angles:** NPS asset-class split; SGB as gold; EPF/PPF as debt (people forget their EPF is often their biggest debt holding).
- **Effort:** M (mapping rules + endpoint + chart). **Value:** high.
- **Pitfalls:** hybrid split is an approximation (label it); "index" category hides debt index funds and target-maturity funds; unpriced holdings at cost still count (fine for allocation).

### 2.2 Target allocation and rebalancing
- **Answers:** "How far am I from my plan? What do I buy/sell to fix it?"
- **Shows:** actual vs target bars per class, drift in % points, "move ₹X from debt to equity", or "direct new money to …" (rebalance with fresh cash avoids tax).
- **Data:** **missing**: target allocation (a per-user settings row: equity/debt/gold/cash %). Rest derivable from 2.1.
- **India angles:** prefer "rebalance with new SIP money" to selling (STCG 20% on equity < 12 months); age-based glide-path hint (e.g. 100 − age) as a default only.
- **Effort:** S once 2.1 exists (+ one settings table, migration). **Value:** high for disciplined investors, medium for others.
- **Pitfalls:** a suggestion to sell is close to advice; phrase as arithmetic ("to reach 60/40 you'd move ₹X"), not a recommendation.

### 2.3 Concentration and exposure
- **Answers:** "Am I too exposed to one stock, fund house, bank, issuer?"
- **Shows:** top 10 holdings by value with % of total; bars by **issuer group**: stocks by company, MF by AMC, FD/RD by bank (merged banks rolled up), bonds by issuer, NPS by PFM; flags e.g. one stock > 10% of equity, one AMC > 30% of MF, one NBFC > X.
- **Data:** derivable (AMC, issuer, PFM exist). **Missing** for stock sector (see 2.17).
- **Effort:** S. **Value:** medium-high.
- **Pitfalls:** an index fund is diversified even if it's 40% of MF; don't flag passive funds like a single stock. Same company in stock + bond + FD (e.g. Bajaj Finance shares and Bajaj Finance FD) should roll up — needs an issuer-to-company link (missing; name match is unreliable; defer).

### 2.4 Bank safety / DICGC exposure
- **Answers:** "Is any bank holding more than ₹5 lakh of mine? Which deposits are uninsured?"
- **Shows:** table per bank (merged banks rolled into the survivor): FD + RD + savings/current, principal + accrued interest, insured amount (min of total and ₹5,00,000), uninsured excess in red; badges: "Not DICGC-insured" (NBFC, HFC — e.g. Bajaj Finance, Shriram), "Co-operative bank", "Small finance bank", "Post Office (sovereign)"; a total "uninsured deposits" KPI.
- **Data:** FD/RD: **exists** (`issuer_id`, `dicgc_insured`, `category`, `merged_into_id`). Manual FDs (no issuer_id) need a name match or "unknown bank" row. Cash: **missing bank link** on `cash_holdings` (needs `issuer_id`, same picker as FD; small migration + form change).
- **India angles:** ₹5L per depositor per bank across all branches and all deposit types, principal + interest; joint accounts and different capacities count separately; Post Office deposits are government-backed, not DICGC; NBFC/HFC deposits have no insurance at all.
- **Effort:** S for FD/RD only; M including cash (migration + picker). **Value:** high (very India-specific, cheap, few apps do it well).
- **Pitfalls:** app has no holder/capacity concept, so it may over-warn for families splitting deposits across names (add a footnote); interest for payout FDs is paid out, so exposure is principal only; DICGC flag is NULL (not false) when unmatched, treat NULL banks as "unknown", not "uninsured".

### 2.5 Liquidity ladder / "what can I access, how fast, at what cost"
- **Answers:** "If I need money, how much can I get in a day, a week, a month, a year?"
- **Shows:** stacked horizontal bar or ladder: **Instant** (cash, savings) → **1–3 days** (liquid/overnight MF, stocks T+1, equity MF T+2/T+3, digital gold) → **Breakable with penalty** (FDs: show ~1% penalty and lost interest; RD) → **Weeks/illiquid** (bonds on exchange, physical gold/jewellery at a discount, SGB only on interest dates after year 5 or on exchange) → **Locked** (PPF until year 7 partial withdrawal, ELSS lots < 3 years, EPF until conditions/retirement, NPS Tier I until 60). Per bucket: amount and % of net worth.
- **Data:** derivable (types, kinds, MF category, ELSS lots from CAS transactions, PPF opened_on, NPS tier, maturity dates). ELSS manual entries: lock-in from the single purchase date.
- **India angles:** PPF partial withdrawal from the 7th FY (limited to 50% of an older balance), loan against PPF years 3–6; NPS Tier I vs Tier II; ELSS 3-year lock per SIP instalment (not per fund); SGB 5-year exit window; FD premature penalty.
- **Effort:** M (rules per type). **Value:** high.
- **Pitfalls:** penalty and exit-load figures vary by bank/AMC; show "approx." and don't compute exact break-costs unless the user enters them.

### 2.6 Emergency-fund coverage
- **Answers:** "How many months could I live on my liquid money?"
- **Shows:** a gauge: (instant + 1–3-day buckets from 2.5, excluding equity optionally) ÷ monthly expenses = N months; target band 6–12 months.
- **Data:** **missing**: monthly expenses (one settings field). Rest derivable from 2.5.
- **Effort:** S after 2.5. **Value:** medium-high.
- **Pitfalls:** counting equity as emergency money is wrong in a crash; default to excluding it.

### 2.7 Maturity calendar and reinvestment planner
- **Answers:** "What's maturing soon, how much will I get, and where am I reinvesting?"
- **Shows:** timeline / list grouped by month for the next 12 months (and a by-year ladder chart for the next 10 years): FD (maturity amount computed), RD, bonds (face × qty or redemption), **SGB maturity and premature-redemption windows**, PPF maturity and extension-block end; "already matured but still in your portfolio" call-out (needs action: renew or close). KPI: ₹ maturing in 30/90/365 days, weighted rate of what's maturing (reinvestment risk if rates fall).
- **Data:** derivable (maturity dates exist for FD/RD/bond/PPF; FD maturity value via `valuation.value_fd(today=maturity)`). SGB windows derivable from `bond_master.issue_date` (every 6 months after year 5).
- **India angles:** FD laddering is common; senior citizens rely on it; SGB windows; PPF extend-with-or-without-contribution decision due within a year of maturity (Form H).
- **Effort:** S–M. **Value:** high.
- **Pitfalls:** RD maturity value assumes every instalment paid; bond redemption at face value (call/put options, amortising bonds not modelled); show the matured count separately since totals exclude them.

### 2.8 Upcoming cash flows (income calendar)
- **Answers:** "What money is coming in and going out, and when?" (retirees, FD-payout users)
- **Shows:** monthly bars for the next 12 months: inflows (payout-FD interest by frequency, bond coupons from `coupon_rate` × face × `interest_frequency`, SGB 2.5% half-yearly on issue price, maturities from 2.7) and outflows (RD instalments due; PPF deposit reminder).
- **Data:** payout FD: exists. Bond coupons: derivable **only for master-linked bonds** with coupon + frequency (manual bonds have only YTM). RD: exists. SIPs: **missing** (not tracked).
- **India angles:** PPF deposit before the 5th of a month earns that month's interest (annual lump sum before 5 April); payout FDs are typical retiree income.
- **Effort:** M. **Value:** medium (high for retirees).
- **Pitfalls:** coupon dates are not stored (only frequency); approximate from issue/maturity date anniversaries; label as estimates.

### 2.9 Net-worth change decomposition ("my saving vs the market")
- **Answers:** "How much did I grow this month / this FY, and how much was my own money?"
- **Shows:** for a chosen period (this month, last month, FY to date, calendar YTD, 1Y): start net worth → + new money invested → + market/interest growth → end net worth (waterfall). Month-by-month table of the same. Builds on the existing chart.
- **Data:** derivable from `/api/networth/history` points (Δinvested = new money, Δcurrent − Δinvested = growth). No new storage.
- **Effort:** S. **Value:** high (the most common monthly question after "how much do I have").
- **Pitfalls:** history is rebuilt from **current** holdings, so sold/deleted holdings disappear from the past and look like "negative new money" never happened; say so. Cash/PF appear as a jump on their `balance_date` (looks like new money). Matured holdings drop out.

### 2.10 Returns: XIRR overall and per asset class
- **Answers:** "What return am I actually earning?"
- **Shows:** XIRR for the whole portfolio and per type and class (equity/debt/gold); absolute gain beside it; a "basis" note (transactions vs purchase date) and an "excluded: N holdings valued at cost" note. Ranked table of holdings by XIRR (best/worst).
- **Data:** derivable: MF from CAS transactions (existing `mf_xirr`), FD (−principal at start, +value today), RD (instalments monthly), bonds, stocks, gold (single flow, already computed in `value_gold`), NPS and PF (**no flows: exclude or use rate as the "return"**; PF's return is its interest rate; NPS can use scheme NAV CAGR over the holding period as a proxy).
- **India angles:** compare debt-side XIRR to post-tax FD; EPF rate as a reference (8.25%).
- **Effort:** M (cash-flow builders per type; solver already exists in `valuation.xirr`). **Value:** high.
- **Pitfalls:** single-date XIRR for SIP-built manual holdings is misleading (understates); holdings valued at cost give 0%; very young holdings (< 3 months) give absurd annualised numbers (show absolute return under 1 year, as most Indian apps do).

### 2.11 Benchmark comparison (vs Nifty, FD, inflation)
- **Answers:** "Did I beat an FD? Inflation? Would a Nifty index fund have done better?"
- **Shows:** your equity XIRR vs "same cash flows into a Nifty 50 index fund" (direct public-market-equivalent); your whole-portfolio XIRR vs an FD rate line vs CPI inflation; growth-of-₹100 line chart.
- **Data:** Nifty: **derivable without a new feed** by using a Nifty 50 index fund's NAV from `mf_nav_history` (e.g. a direct-growth Nifty 50 index fund; NAV ≈ TRI minus ~0.2% cost; history fetched on demand from mfapi.in). Sensex/Nifty 500/midcap similarly via their index funds. FD reference: **missing** (seed a constant, e.g. SBI 1-year rate history, or use the user's own weighted FD rate). CPI: **missing** (MOSPI monthly CPI; a small hand-updated seed CSV, or a fixed 5–6% assumption).
- **India angles:** compare against TRI, not the price index (price index understates by ~1.2–1.5%/yr dividends); post-tax FD comparison is more honest for a 30% slab payer.
- **Effort:** M (benchmark cash-flow replay + seed for CPI/FD). **Value:** high for the equity part, medium for inflation.
- **Pitfalls:** benchmark replay needs your real cash-flow dates; with single-date manual holdings it's a lump-sum comparison; picking one index for a mid/small-cap-heavy portfolio is unfair (offer Nifty 500 too).

### 2.12 Today's change and movers (daily widget)
- **Answers:** "How much did I make today? What moved?"
- **Shows:** "Today: +₹12,340 (+0.42%)" on the dashboard, split stocks / MF / NPS; top 5 gainers and losers.
- **Data:** exists (stock `prev_close`, MF and NPS `day_change` already in items).
- **Effort:** S. **Value:** medium (high engagement, low decision value).
- **Pitfalls:** dates don't line up (stock close at 19:30 IST, MF NAV late night, NPS next day); label each with its date, or only sum items whose price date is the latest trading day.

### 2.13 Debt portfolio: yield, quality, duration
- **Answers:** "What does my fixed income earn on average? How risky is it? When does it roll off?"
- **Shows:** weighted average rate (FD/RD rate, bond YTM, PF rate, savings rate where given); split by issuer type (PSU bank, private bank, SFB, co-op, NBFC/HFC, government/SDL, PSU bond, corporate AAA/AA/below, tax-free); maturity profile (< 1y, 1–3y, 3–5y, 5y+); avg years to maturity.
- **Data:** derivable (issuer category, bond rating, PSU ownership exist). Debt MF yield/duration: **missing** (AMFI factsheet data); show them as a separate unknown-duration bucket.
- **India angles:** SFB FDs pay more but carry more risk; NBFC FDs uninsured; tax-free bonds (yield is post-tax — show a tax-equivalent yield given the slab); RBI rate-cut cycle → reinvestment risk.
- **Effort:** S–M. **Value:** medium-high (FD-heavy Indian portfolios).
- **Pitfalls:** ratings stale (`rating_as_of`); manual bonds have no rating.

### 2.14 Interest income this FY and TDS projection
- **Answers:** "How much interest do I have to declare? Will the bank cut TDS? Should I submit 15G/15H?"
- **Shows:** per bank: interest accrued in the FY (FD cumulative accrual, payout FD interest paid, RD), against the TDS threshold (₹50,000 per bank per FY, ₹1,00,000 for senior citizens; verify current numbers) with a progress bar; projected TDS at 10%; plus savings interest (80TTA ₹10,000 / 80TTB ₹50,000 seniors, old regime) where a rate is given; bond interest (coupons for linked bonds); EPF interest taxable portion note; total "Income from other sources" estimate for ITR.
- **Data:** derivable: FD/RD accrual for a date range = `value_*(as of FY end or today) − value_*(as of FY start)` (the valuation functions already take a date). Savings interest: rough, from optional rate × balance. **Missing:** senior-citizen flag, tax regime.
- **India angles:** banks deduct TDS on accrued interest of cumulative FDs every year even though you get nothing until maturity — users are routinely surprised. 15G/15H only if total income is below the exemption limit. TDS is per bank (all branches), so merged banks matter.
- **Effort:** M. **Value:** high at tax time (Jan–Apr), low otherwise.
- **Pitfalls:** banks compute accrual their own way (quarterly compounding by FY); the estimate will differ by a few rupees; never present as a TDS certificate; Form 26AS/AIS is the truth.

### 2.15 Capital gains: unrealised by holding period ("if I sold today")
- **Answers:** "If I sell this, is it STCG or LTCG, and roughly how much tax?"
- **Shows:** per holding and per lot: holding period, ST/LT status, days until it turns long-term ("LT in 23 days" — very actionable), unrealised gain split ST/LT; totals by tax bucket.
- **Rules (verify per tax year; config table):**
  - Listed equity shares, equity-oriented MFs (≥ 65% domestic equity, incl. arbitrage and most balanced-advantage funds), equity ETFs: LT after 12 months; LTCG 12.5% above ₹1.25L per FY; STCG 20%.
  - Grandfathering for equity bought before 1 Feb 2018: cost = max(actual cost, min(FMV on 31 Jan 2018, sale price)).
  - Debt MFs bought on or after 1 Apr 2023 (specified MFs): slab rate regardless of holding period. Bought before: LT after 24 months, 12.5% without indexation.
  - Gold ETFs: LT after 12 months; gold/international FoFs and physical/digital gold: LT after 24 months; LTCG 12.5%; ST at slab.
  - Listed bonds: LT after 12 months, 12.5%; unlisted bonds/debentures: slab always. SGB: RBI redemption exempt for individuals (check current eligibility rules for secondary-market buyers); exchange sale LT after 12 months.
- **Data:** MF lots: derivable from CAS `mf_transactions` (FIFO, redemptions consume oldest lots; `networth.units_and_cost_at` already does FIFO). Manual MF: one lot. Stocks: one lot per row. Gold, bonds: one lot. 31-Jan-2018 FMV: MF derivable (`mf_nav_history` 10 years); stocks **missing** (one-off fetch of the 31 Jan 2018 bhavcopy for held ISINs). Listed/unlisted bond flag: **missing** (derivable from `nse_symbol` present in `bond_master`, approximately). Slab rate: **missing** (user input).
- **Effort:** L (rules engine, lot builder, config, grandfathering). **Value:** high before sales and in Feb–Mar; low otherwise.
- **Pitfalls:** stamp duty/STT/brokerage not in cost; switches between plans are sales; bonus/split lots; dividend stripping rules; the "65% equity" test is on the fund's portfolio, not its category name. Show "estimate, not tax advice".

### 2.16 Tax-gain harvesting helper (equity LTCG ₹1.25L)
- **Answers:** "How many units can I sell and re-buy this year to use my tax-free LTCG allowance?"
- **Shows:** LTCG already realised this FY (from CAS redemptions; stocks missing), remaining headroom to ₹1.25L, and per fund the units of LT lots that would realise exactly the headroom; also tax-loss harvesting (ST losses that offset ST/LT gains).
- **Data:** needs 2.15 + realised gains this FY. MF realised: derivable from CAS redemptions (FIFO). Stocks realised: **missing** (sales are deletes).
- **India angles:** popular Indian feature (Kuvera, Groww). ELSS lots under 3 years can't be sold. Exit load if < 1 year.
- **Effort:** M on top of 2.15. **Value:** medium-high, once a year (Feb–Mar). A real ₹ saving.
- **Pitfalls:** incomplete realised history → wrong headroom; must loudly ask "did you sell anything else this year?"; re-buying creates a new lot (re-import CAS).

### 2.17 Equity breakdown: market cap and sector
- **Answers:** "Am I too much in small caps? Too much in banks/IT?"
- **Shows:** large/mid/small/flexi split (MF from `amfi_category`; stocks by AMFI's half-yearly market-cap list); sector split for direct stocks.
- **Data:** MF cap: derivable from `amfi_category` (flexi/multi-cap stays a separate bucket). Stock market cap: **missing** (AMFI half-yearly "average market capitalisation" list: top 100 large, 101–250 mid, rest small; an Excel file twice a year; seed import). Stock sector: **missing** (NSE index constituent CSVs, e.g. Nifty 500 list, carry an "Industry" column; covers the 500 most traded names; others "Unclassified").
- **Effort:** M (one new seed/import each). **Value:** medium.
- **Pitfalls:** MF sector exposure needs look-through (see "not building"); mixing direct-stock sector with fund category looks precise but isn't.

### 2.18 MF portfolio hygiene
- **Answers:** "Am I paying too much? Holding duplicates? Wrong options?"
- **Shows:** checklist cards: regular-plan funds (₹ in regular plans; direct plans typically cost 0.5–1%/yr less), IDCW options (dividend taxed at slab yearly; growth defers tax), duplicate sub-categories (e.g. three large-cap funds), too many funds (> 10–12), tiny positions (< 1% of MF), funds held via several platforms, schemes no longer active.
- **Data:** derivable (`plan`, `option`, `amfi_category`, `is_active` in `mf_master`; `platform` on holding). Expense ratio / exact savings: **missing** (AMFI TER data; defer, show qualitative).
- **India angles:** regular vs direct is the single biggest silent cost for Indian MF investors; switching triggers capital gains and exit load, so show the switch cost next to the saving (needs 2.15 for accuracy; show a caution otherwise).
- **Effort:** S. **Value:** medium-high (one-off big win).
- **Pitfalls:** the user may want regular plans (advisor relationship); phrase as facts, not instructions.

### 2.19 Data health / freshness
- **Answers:** "Can I trust these numbers?"
- **Shows:** list of issues with "fix" links to the edit dialog: holdings valued at cost (no price/NAV/rate; manual MFs, unlinked stocks), cash and PF balances older than 3–6 months, matured FDs/RDs/bonds still open, CAS last imported N days ago (MF transactions stale → XIRR basis drops to purchase date), latest price/NAV dates, SGBs valued by YTM.
- **Data:** derivable (all flags exist: `master_id`, `scheme_code`, `balance_date`, `matured_count`, `nav_date`, `price_time`).
- **Effort:** S. **Value:** high as an enabler: every other analytic is only as good as this.
- **Pitfalls:** don't nag; one compact card with a count, expandable.

### 2.20 Retirement buckets: EPF, PPF, NPS projections
- **Answers:** "What will my PPF/EPF/NPS be worth at maturity / at 60?"
- **Shows:** PPF: projected value at maturity and at each 5-year extension, with and without yearly deposits; EPF: projected balance at retirement age given current rate and an assumed monthly contribution; NPS: projected corpus at 60 under an assumed return per asset class, and the lump-sum/annuity split at exit.
- **Data:** PPF maturity: exists. Age/retirement age, future contributions: **missing** (user inputs). NPS exit rules: config (recently revised by PFRDA; verify).
- **India angles:** PPF interest on the lowest balance between the 5th and month-end; EPF rate declared yearly (8.25%); NPS Tier I lock to 60; 80CCD(1B) extra ₹50k (old regime).
- **Effort:** M. **Value:** medium (high for 40+).
- **Pitfalls:** projections look authoritative; show assumptions on the card and let the user change them.

### 2.21 Tax-saving tracker (80C, 80CCD(1B), 80TTA)
- **Answers:** "How much of my ₹1.5L 80C have I used this FY? Do I need to invest more before 31 March?"
- **Shows:** progress bars: 80C (ELSS purchases this FY + PPF deposits this FY + EPF/VPF employee contributions + tax-saver FDs + other items the user types in: insurance, tuition, home-loan principal), 80CCD(1B) NPS ₹50k, 80TTA savings interest.
- **Data:** ELSS this FY: derivable from CAS purchases (`mf_transactions`, category elss). PPF/EPF/NPS contributions per FY: **missing** (no contribution log). Tax-saver FD flag: **missing**. Other 80C items: **missing** (not assets). Regime: **missing**.
- **India angles:** only matters in the **old regime**; the new regime is default since FY 2023-24 and allows only employer NPS 80CCD(2). Section numbers change under the 2025 Act.
- **Effort:** M–L (contribution logs for three asset types). **Value:** high **only if the user is on the old regime**, otherwise near zero.
- **Pitfalls:** half the inputs aren't investments; partial data gives a falsely low "used" figure that pushes the user to over-invest.

### 2.22 Goals ("Am I on track?")
- **Answers:** "Will I have ₹X by year Y for retirement / education / house?"
- **Shows:** goal cards: target (inflation-adjusted), linked holdings or % of classes, projected value at assumed returns, required monthly SIP to close the gap, on-track/behind badge.
- **Data:** **missing**: goals table (name, target, date, inflation, linked holdings/classes, expected return). Derivable once entered.
- **Effort:** M–L (new CRUD, forms, validation in API + forms with identical wording, projection maths). **Value:** high in principle, but only if the user maintains it.
- **Pitfalls:** heavy input; double-allocating one holding to two goals; assumptions dominate the answer.

### 2.23 Year in review (FY report)
- **Answers:** "What happened this year?"
- **Shows:** opening and closing net worth, new money, growth, interest earned (2.14), realised gains (MF from CAS), best and worst holdings, allocation then vs now, maturities handled; printable/PDF-ish page.
- **Data:** mostly derivable; realised stock gains missing; past allocation derivable from history only for current holdings.
- **Effort:** M (composes 2.1, 2.9, 2.10, 2.14). **Value:** medium (yearly).

### 2.24 Gold & silver summary
- **Answers:** "How much gold do I own in grams across forms, and what's it worth?"
- **Shows:** total grams by metal and purity (24K-equivalent grams), split physical / digital / SGB / gold ETF / gold FoF; value at IBJA; gold % of net worth (common guidance 5–15%).
- **Data:** gold holdings exist; SGB grams = bond quantity (derivable); ETF/FoF grams: not meaningful (value only).
- **Effort:** S. **Value:** medium (gold is culturally large in Indian households, often the largest undeclared asset).
- **Pitfalls:** jewellery value at IBJA rate overstates resale value (making charges lost, purity deduction); label "metal value".

### 2.25 Allocation over time
- **Answers:** "How has my mix drifted?"
- **Shows:** 100% stacked area by class over 1Y/All.
- **Data:** derivable by extending `build_history` to return per-type current values (it values each holding per date already).
- **Effort:** S–M. **Value:** medium-low (interesting, rarely decision-making).

### 2.26 Holding-level P&L heatmap / treemap
- **Answers:** "Which holdings are big and which are red?"
- **Shows:** treemap sized by value, coloured by gain %.
- **Data:** exists.
- **Effort:** S. **Value:** low-medium (pretty; most of its value is in 2.3 and 2.10 tables).

---

## 3. Ranking and first slice

### Scoring (value ÷ effort, data readiness, dependencies)

| Rank | Item | Value | Effort | Data | Why here |
|---|---|---|---|---|---|
| 1 | **2.1 Asset-class allocation** (+ 2.3 concentration as a section) | High | M | Derivable | The question users ask most after "how much". Builds the class-mapping layer (equity/debt/gold/cash, SGB → gold, NPS E/C/G, ETF names) that 2.2, 2.5, 2.6, 2.11, 2.17, 2.25 all reuse. |
| 2 | **2.7 Maturity calendar** (+ matured-but-open call-out) | High | S–M | Derivable | Concrete, recurring action ("₹3.2L matures on 14 Dec"); FD/RD/bond/PPF dates already stored; reuses `value_fd`. |
| 3 | **2.4 Bank safety / DICGC** | High | S (FD/RD) → M (+cash bank link) | Exists for FD/RD; cash needs `issuer_id` | Uniquely Indian, cheap, the issuer master was built for exactly this. |
| 4 | **2.9 Net-worth change decomposition** | High | S | Derivable from existing history endpoint | Answers the monthly "my saving vs market" question with zero new data. |
| 5 | **2.5 Liquidity ladder** (+ 2.6 emergency coverage once expenses are entered) | High | M | Derivable (+1 setting) | Uses the class/lock-in rules from #1; the "what can I get in an emergency" view is rare in Indian apps and valuable. |
| 6 | **2.10 + 2.11 Returns and benchmark** | High | M | Derivable (Nifty via an index fund NAV); CPI/FD seed missing | The "did I beat FD/Nifty" question; needs per-type cash flows. Comes after #7 so unpriced/stale holdings are flagged first. |
| 7 | **2.19 Data health** (with 2.18 MF hygiene) | High (enabler) / medium-high | S | Derivable | Cheap; makes every number above trustworthy; hygiene finds the regular-plan and IDCW leaks. |

Next wave (tax season, Jan–Mar 2027 is the natural deadline): **2.14 Interest income + TDS** (M, high seasonal), then **2.15/2.16 Capital gains and harvesting** (L, high seasonal; needs a lot builder and a config table, and works fully only for CAS-imported MFs).

Later: 2.2 target allocation (S once #1 exists, needs one settings row), 2.13 debt quality, 2.8 cash-flow calendar, 2.12 today's change on the dashboard (S, nice quick win any time), 2.24 gold summary, 2.20 retirement projections, 2.22 goals, 2.23 year in review.

### Recommended first slice: one `/analytics` page, "Overview"

One new sidebar entry ("Analytics"), one API endpoint `GET /api/analytics/overview` that calls `load_groups()` once, joins the master fields it needs, and returns all sections (pure maths in `services/analytics.py`, unit-tested like `services/networth.py`). Sections, top to bottom:

1. **Allocation**: donut by class (Equity / Debt / Gold & silver / Cash), "include retirement accounts" toggle, drill-down table class → type → holding. SGB counted as gold; hybrid funds in their own "Hybrid" slice (no guessed split in v1).
2. **Concentration**: top 10 holdings (% of total), and bars for largest AMC, bank, bond issuer, stock.
3. **Coming up**: maturities in the next 90 days and next 12 months (amount at maturity, rate), plus "N holdings already matured" with links.
4. **Bank safety**: per-bank FD + RD exposure (merged banks rolled up), insured vs above ₹5L, uninsured NBFC/HFC deposits flagged. Cash accounts noted as "not linked to a bank yet".
5. **Liquidity**: ladder bars (instant / days / breakable / illiquid / locked).
6. **Data health** strip: count of holdings at cost, stale balances, matured-but-open; expandable.

Why this slice: zero new tables or external data, one endpoint, all five sections reuse the same valued items and the same class mapping, and it answers the four most frequent non-tax questions (where, how concentrated, what's coming, how safe/liquid). Roughly 4–5 builder tasks: (a) class mapping + service + tests, (b) endpoint + schema, (c) page shell + allocation/concentration UI, (d) maturities/bank safety/liquidity UI, (e) data-health strip + docs.

Slice 2: net-worth change waterfall (onto the existing chart or the analytics page), returns per class with basis notes, Nifty index-fund benchmark. Slice 3 (before Jan 2027): interest-income/TDS by bank, then capital gains.

Small prerequisite worth doing alongside slice 1 (separate change, needs your OK since it changes behaviour): **value SGBs at grams × IBJA 999** instead of YTM accrual. Otherwise both the dashboard and the allocation understate (or misstate) gold.

---

## 4. What not to build (or defer), and why

| Idea | Decision | Reason |
|---|---|---|
| Sharpe, Sortino, beta, volatility, max drawdown, alpha | Skip | Fund-manager metrics; a personal user makes no decision from them; manual and at-cost holdings make the series noisy and the numbers falsely precise. |
| Monte Carlo retirement simulations | Skip | Assumption-driven; a simple deterministic projection (2.20) answers the same question honestly. |
| MF portfolio look-through (stock overlap between funds, true sector exposure) | Defer indefinitely | Needs monthly portfolio disclosures from ~45 AMCs in inconsistent Excel formats; L effort with ongoing maintenance. Category-level duplicate detection (2.18) gets 80% of the value. |
| Expense-ratio (TER) savings calculator | Defer | AMFI TER data is a separate, messy daily source. Plan direct/regular already flags the issue qualitatively. |
| ITR-ready capital-gains statement (Schedule 112A export) | Skip | Filing-grade output needs complete sale history, corporate actions, STT and exact grandfathering for every stock; the app deletes sold holdings. A wrong filing is worse than no feature. Keep 2.15 as an estimate. |
| 80C / 80CCD tracker before contributions are logged | Defer until (a) user confirms old regime, (b) per-FY contribution logs exist for PPF/EPF/NPS | With today's data it would show only ELSS and understate usage, nudging over-investment. Near-zero value on the new regime. |
| Goals with linked holdings | Defer to after slices 1–3 | Highest input burden; value depends on the user keeping it current. Revisit once allocation and returns exist (goals reuse both). |
| Realised P&L for stocks / lifetime returns including sold holdings | Defer, but note the root cause | Needs a "sell" action that records a sale instead of deleting (a product change to the portfolio, not an analytics screen). Worth discussing because it unlocks tax and true returns. |
| Intraday / real-time P&L, price alerts | Skip | No live source (Yahoo blocks servers, Upstox needs an account); nightly closes are enough for long-term investing. |
| Daily P&L calendar heatmap, treemap as a headline | Low priority | Vanity: engaging but decision-free; tables in 2.3/2.10 carry the information. |
| Stock fundamentals (P/E, 52-week high/low, dividends) | Skip | Out of scope for a wealth tracker; data sources are paid or scrape-only. |
| Credit-score, insurance cover, loan tracking | Out of scope for analytics | But note: without liabilities, "net worth" is gross assets. A "Loans" type would be a new asset class, not an analytics screen. |
| Family / multi-holder views | Defer | No holder concept; DICGC per-depositor logic and tax would need it. Only if the user manages family money. |
| Stock sector/market-cap before a source is picked | Defer to after slice 2 | Needs AMFI cap list + Nifty 500 industry seed; MF category already gives a cap split for funds. |

---

## 5. Open questions for the user

1. **Tax regime**: old or new? Decides whether the 80C/80CCD tracker is worth anything.
2. **Senior citizen** (or holdings for one)? Changes TDS (₹1L) and 80TTB thresholds.
3. **Target allocation**: do you want to set one (equity/debt/gold/cash %)? Needs a small settings table.
4. **Monthly expenses** for emergency-fund coverage: OK to store one number?
5. **Retirement money in allocation**: count EPF/PPF/NPS in the main mix, or show them separately by default?
6. **Hybrid funds**: own slice (simple, honest) or split by a typical equity share per sub-category (approximate)?
7. **Bank link for cash accounts** (needed for full DICGC exposure): add the FD/RD bank picker to Cash & Savings?
8. **SGB valuation**: switch SGBs to grams × IBJA 999 rate (behaviour change)?
9. **Selling**: keep deleting sold holdings, or add a "Sell" action that records realised gains? (Unlocks capital-gains and true returns.)
10. **Benchmark**: Nifty 50 (via an index fund NAV) as default? Need inflation (CPI seed) or is an FD-rate line enough?
11. **Where it lives**: a new "Analytics" sidebar page, or extra dashboard cards?

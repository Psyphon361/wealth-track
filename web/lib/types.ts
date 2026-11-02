export type AssetType = "fd" | "rd" | "stock" | "bond" | "mf" | "gold" | "cash" | "pf" | "nps";

export const ASSET_TYPE_LABELS: Record<AssetType, string> = {
  fd: "Fixed Deposits",
  rd: "Recurring Deposits",
  stock: "Stocks",
  bond: "Bonds",
  mf: "Mutual Funds",
  gold: "Gold & Silver",
  cash: "Cash & Savings",
  pf: "EPF & PPF",
  nps: "NPS",
};

export type Compounding =
  | "monthly"
  | "quarterly"
  | "half_yearly"
  | "yearly"
  | "simple";
export type PayoutType = "cumulative" | "payout";
export type Exchange = "NSE" | "BSE";
export type BondType = "government" | "corporate" | "tax_free" | "sgb" | "other";
export type MFCategory =
  | "equity"
  | "debt"
  | "hybrid"
  | "index"
  | "elss"
  | "liquid"
  | "other";

export const COMPOUNDING_LABELS: Record<Compounding, string> = {
  monthly: "Monthly",
  quarterly: "Quarterly",
  half_yearly: "Half-yearly",
  yearly: "Yearly",
  simple: "Simple",
};

export const PAYOUT_TYPE_LABELS: Record<PayoutType, string> = {
  cumulative: "Cumulative",
  payout: "Payout",
};

export const EXCHANGE_LABELS: Record<Exchange, string> = {
  NSE: "NSE",
  BSE: "BSE",
};

export const BOND_TYPE_LABELS: Record<BondType, string> = {
  government: "Government",
  corporate: "Corporate",
  tax_free: "Tax-free",
  sgb: "SGB",
  other: "Other",
};

export type CashKind = "savings" | "current" | "cash" | "other";

export const CASH_KIND_LABELS: Record<CashKind, string> = {
  savings: "Savings account",
  current: "Current account",
  cash: "Cash in hand",
  other: "Other",
};

export type PfKind = "epf" | "vpf" | "ppf";

export const PF_KIND_LABELS: Record<PfKind, string> = {
  epf: "EPF",
  vpf: "VPF",
  ppf: "PPF",
};

export type NpsTier = "I" | "II";
export type NpsAssetClass = "E" | "C" | "G" | "A" | "other";

export const NPS_TIER_LABELS: Record<NpsTier, string> = {
  I: "Tier I",
  II: "Tier II",
};

export const NPS_ASSET_CLASS_LABELS: Record<NpsAssetClass, string> = {
  E: "Equity",
  C: "Corporate debt",
  G: "Govt securities",
  A: "Alternative",
  other: "Other",
};

export type GoldForm = "jewellery" | "coin" | "bar" | "digital";
export type GoldMetal = "gold" | "silver";
export type GoldPurity = "999" | "995" | "916" | "750" | "585" | "925";

export const GOLD_METAL_LABELS: Record<GoldMetal, string> = {
  gold: "Gold",
  silver: "Silver",
};

/** Purities valid per metal (same rule as the API). */
export const GOLD_PURITIES_BY_METAL: Record<GoldMetal, GoldPurity[]> = {
  gold: ["999", "995", "916", "750", "585"],
  silver: ["999", "925"],
};

export const GOLD_FORM_LABELS: Record<GoldForm, string> = {
  jewellery: "Jewellery",
  coin: "Coin",
  bar: "Bar",
  digital: "Digital",
};

export const GOLD_PURITY_LABELS: Record<GoldPurity, string> = {
  "999": "24K (999)",
  "995": "24K (995)",
  "916": "22K (916)",
  "750": "18K (750)",
  "585": "14K (585)",
  "925": "925 (sterling)",
};

/** Purity label for a holding; 999 reads differently for gold (24K) and silver (fine). */
export function goldPurityLabel(metal: GoldMetal, purity: GoldPurity): string {
  if (metal === "silver" && purity === "999") return "999 (fine)";
  return GOLD_PURITY_LABELS[purity];
}

/** Purity filter facet labels: 999 is shared by both metals. */
export const GOLD_PURITY_FACET_LABELS: Record<GoldPurity, string> = {
  ...GOLD_PURITY_LABELS,
  "999": "999 (24K / fine)",
};

export const MF_CATEGORY_LABELS: Record<MFCategory, string> = {
  equity: "Equity",
  debt: "Debt",
  hybrid: "Hybrid",
  index: "Index",
  elss: "ELSS",
  liquid: "Liquid",
  other: "Other",
};

// Input types (request bodies)

export interface FixedDepositInput {
  issuer_id: number | null;
  bank: string;
  label: string | null;
  principal: number;
  rate: number;
  start_date: string;
  tenure_years: number;
  tenure_months: number;
  tenure_days: number;
  compounding: Compounding;
  payout_type: PayoutType;
  notes: string | null;
}

export interface RecurringDepositInput {
  issuer_id: number | null;
  bank: string;
  label: string | null;
  monthly_instalment: number;
  rate: number;
  start_date: string;
  tenure_years: number;
  tenure_months: number;
  tenure_days: number;
  compounding: Compounding;
  notes: string | null;
}

export type FdIssuerCategory =
  | "public_sector"
  | "private_sector"
  | "small_finance"
  | "foreign"
  | "regional_rural"
  | "local_area"
  | "payments"
  | "state_coop"
  | "district_coop"
  | "urban_coop"
  | "nbfc"
  | "hfc"
  | "post_office";

export const FD_ISSUER_CATEGORY_LABELS: Record<FdIssuerCategory, string> = {
  public_sector: "Public sector bank",
  private_sector: "Private bank",
  small_finance: "Small finance bank",
  foreign: "Foreign bank",
  regional_rural: "Regional rural bank",
  local_area: "Local area bank",
  payments: "Payments bank",
  state_coop: "State co-op bank",
  district_coop: "District co-op bank",
  urban_coop: "Urban co-op bank",
  nbfc: "NBFC",
  hfc: "Housing finance co.",
  post_office: "India Post",
};

export interface FdIssuer {
  id: number;
  code: string;
  name: string;
  short_name: string | null;
  category: FdIssuerCategory;
  regulator: string | null;
  reg_no: string | null;
  dicgc_insured: boolean | null;
  accepts_deposits: boolean;
  merged_into: { id: number; name: string } | null;
  merged_on: string | null;
  is_active: boolean;
}

export interface StockMaster {
  id: number;
  isin: string;
  kind: "stock" | "etf";
  name: string;
  nse_symbol: string | null;
  nse_series: string | null;
  bse_code: string | null;
  bse_symbol: string | null;
  bse_group: string | null;
  face_value: number | null;
  is_active: boolean;
}

export interface BondMaster {
  id: number;
  isin: string;
  name: string;
  issuer: string | null;
  nse_symbol: string | null;
  nse_series: string | null;
  face_value: number | null;
  coupon_rate: number | null;
  maturity_date: string | null;
  bond_type: BondType;
  is_active: boolean;
  issue_date: string | null;
  issue_price: number | null;
  rating: string | null;
  rating_agency: string | null;
  rating_as_of: string | null;
  coupon_type: string | null;
  interest_frequency: string | null;
}

export interface StockInput {
  master_id: number | null;
  name: string;
  symbol: string | null;
  exchange: Exchange;
  broker: string | null;
  quantity: number;
  avg_buy_price: number;
  buy_date: string;
  notes: string | null;
}

export interface BondInput {
  master_id: number | null;
  name: string;
  isin: string | null;
  issuer: string;
  bond_type: BondType;
  platform: string | null;
  quantity: number;
  face_value: number | null;
  purchase_price: number;
  invested_amount: number;
  purchase_date: string;
  ytm: number;
  maturity_date: string;
  notes: string | null;
}

export type MfPlan = "direct" | "regular";
export type MfOption = "growth" | "idcw" | "bonus" | "other";

export interface MfScheme {
  scheme_code: number;
  name: string;
  amc: string;
  plan: MfPlan | null;
  option: MfOption | null;
  idcw_frequency: string | null;
  amfi_category: string | null;
  category: MFCategory;
  nav: number | null;
  nav_date: string | null;
  isin_growth_payout: string | null;
  isin_reinvest: string | null;
}

export interface MfNavResponse {
  scheme_code: number;
  requested_date: string;
  nav_date: string;
  nav: number;
  source: "latest" | "history";
}

export interface NpsScheme {
  scheme_id: string;
  scheme_name: string;
  pfm_name: string;
  tier: NpsTier | null;
  asset_class: NpsAssetClass;
  nav: number | null;
  nav_date: string | null;
}

export interface GoldRateResponse {
  metal?: GoldMetal;
  purity: string;
  requested_date: string;
  rate_date: string;
  rate_per_gram: number;
}

export interface MutualFundInput {
  scheme_code: number | null;
  scheme_name: string;
  platform: string | null;
  category: MFCategory;
  units: number;
  avg_nav: number;
  invested_amount: number;
  purchase_date: string;
  notes: string | null;
}

export interface GoldInput {
  name: string;
  metal: GoldMetal;
  form: GoldForm;
  purity: GoldPurity;
  weight_grams: number;
  purchase_date: string;
  invested_amount: number;
  notes: string | null;
}

export interface CashInput {
  name: string;
  kind: CashKind;
  balance: number;
  interest_rate: number | null;
  balance_date: string;
  notes: string | null;
}

export interface PfInput {
  name: string;
  kind: PfKind;
  balance: number;
  balance_date: string;
  interest_rate: number;
  contributed: number | null;
  opened_on: string | null;
  notes: string | null;
}

export interface NpsInput {
  scheme_id: string;
  units: number;
  contributed: number;
  start_date: string;
  notes: string | null;
}

// CAS import

export interface CasExistingHolding {
  id: number;
  units: number;
  invested_amount: number;
  avg_nav: number;
  purchase_date: string;
}

export interface CasTransaction {
  date: string;
  type: "purchase" | "redemption";
  amount: number;
  units: number;
}

export interface CasPreviewRow {
  key: string;
  scheme_code: number | null;
  scheme_name: string;
  amc: string;
  plan: MfPlan | null;
  option: MfOption | null;
  category: MFCategory;
  isin: string;
  folios: string[];
  units: number;
  invested_amount: number;
  avg_nav: number;
  purchase_date: string | null;
  current_value: number | null;
  existing: CasExistingHolding[];
  transactions: CasTransaction[];
  importable: boolean;
  issue: string | null;
}

export interface CasPreview {
  statement_from: string;
  statement_to: string;
  rows: CasPreviewRow[];
  hidden_zero: number;
}

export interface CasCommitRow {
  action: "create" | "update";
  holding_id: number | null;
  scheme_code: number | null;
  scheme_name: string;
  category: MFCategory;
  units: number;
  avg_nav: number;
  invested_amount: number;
  purchase_date: string | null;
  transactions: CasTransaction[];
}

export interface CasCommitResult {
  message: string;
  description: string;
  created: number;
  updated: number;
}

// Record types (responses)

export interface RecordFields {
  id: number;
  created_at: string;
  updated_at: string;
}

export type FixedDeposit = FixedDepositInput & RecordFields;
export type RecurringDeposit = RecurringDepositInput & RecordFields;
export type Stock = StockInput & RecordFields;
export type Bond = BondInput & RecordFields;
export type MutualFund = MutualFundInput & RecordFields;
export type Gold = GoldInput & RecordFields;
export type Cash = CashInput & RecordFields;
export type Pf = PfInput & RecordFields;
export type Nps = NpsInput &
  RecordFields & {
    scheme_name: string;
    pfm_name: string;
    tier: NpsTier | null;
    asset_class: NpsAssetClass;
  };

export type AssetRecord =
  | FixedDeposit
  | RecurringDeposit
  | Stock
  | Bond
  | MutualFund
  | Gold
  | Cash
  | Pf
  | Nps;

// Portfolio

export interface ComputedFields {
  invested: number;
  current_value: number;
  gain: number;
  gain_pct: number;
  interest_received?: number | null;
  maturity_date?: string;
  status: "active" | "matured";
}

export type PortfolioItem = AssetRecord & ComputedFields;

export interface Totals {
  invested: number;
  current_value: number;
  gain: number;
  gain_pct: number;
}

export interface PortfolioGroup {
  type: AssetType;
  label: string;
  items: PortfolioItem[];
  totals: Totals;
}

export interface PortfolioResponse {
  groups: PortfolioGroup[];
}

export interface DashboardByType {
  type: AssetType;
  label: string;
  count: number;
  matured_count: number;
  invested: number;
  current: number;
  allocation_pct: number;
}

export interface DashboardResponse {
  total_invested: number;
  total_current: number;
  total_gain: number;
  gain_pct: number;
  by_type: DashboardByType[];
}

// Holdings grids (GET /holdings/{type})

export type HoldingStatus = "active" | "matured";
export type SortDir = "asc" | "desc";

export type FixedDepositItem = FixedDeposit & ComputedFields;
export type RecurringDepositItem = RecurringDeposit & ComputedFields;
export type StockItem = Stock &
  ComputedFields & {
    price: number | null;
    prev_close: number | null;
    day_change_pct: number | null;
    price_time: string | null;
    price_source: "bhavcopy" | null;
  };
export type BondItem = Bond & ComputedFields;
export type MutualFundItem = MutualFund &
  ComputedFields & {
    nav: number | null;
    nav_date: string | null;
    prev_nav: number | null;
    prev_nav_date: string | null;
    day_change: number | null;
    day_change_pct: number | null;
    // MF XIRR (grid rows and details)
    xirr?: number | null;
    xirr_basis?: "transactions" | "purchase_date" | null;
    xirr_transactions?: number;
  };

export type GoldItem = Gold &
  ComputedFields & {
    rate_per_gram: number | null;
    rate_date: string | null;
    xirr?: number | null;
  };

export type CashItem = Cash &
  ComputedFields & {
    xirr?: number | null;
  };

export type PfItem = Pf &
  Omit<ComputedFields, "maturity_date"> & {
    accrued_interest: number;
    maturity_date: string | null;
    extended_until: string | null;
    xirr?: number | null;
  };

export type NpsItem = Nps &
  ComputedFields & {
    nav: number | null;
    nav_date: string | null;
    prev_nav: number | null;
    prev_nav_date: string | null;
    day_change: number | null;
    day_change_pct: number | null;
  };

export type HoldingRow =
  | FixedDepositItem
  | RecurringDepositItem
  | StockItem
  | BondItem
  | MutualFundItem
  | GoldItem
  | CashItem
  | PfItem
  | NpsItem;

export interface FacetValue {
  value: string;
  count: number;
}

export interface HoldingsSummary {
  count: number;
  matured_count: number;
  invested: number;
  current_value: number;
  gain: number;
  gain_pct: number;
}

export interface HoldingsResponse<TRow extends HoldingRow = HoldingRow> {
  items: TRow[];
  total: number;
  page: number;
  page_size: number;
  page_count: number;
  summary: HoldingsSummary;
  facets: Record<string, FacetValue[]>;
  prices_as_of?: string | null;
}

// Holding details (GET /holdings/{type}/{id})

export type HoldingMaster = FdIssuer | StockMaster | BondMaster | MfScheme | NpsScheme;

export interface HoldingDetailResponse<TItem extends HoldingRow = HoldingRow> {
  item: TItem;
  master: HoldingMaster | null;
}

// Net worth history (GET /networth/history)

export type NetWorthRange = "1m" | "6m" | "1y" | "all";

export interface NetWorthPoint {
  date: string;
  invested: number;
  current: number;
}

export interface DeletedHolding {
  type: AssetType;
  type_label: string;
  id: number;
  name: string;
  deleted_at: string;
  purge_on: string;
  days_left: number;
}

export interface NetWorthHistory {
  range: NetWorthRange;
  points: NetWorthPoint[];
  stocks_at_cost_before: string | null;
}

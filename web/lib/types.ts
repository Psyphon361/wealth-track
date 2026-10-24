export type AssetType = "fd" | "rd" | "stock" | "bond" | "mf";

export const ASSET_TYPE_LABELS: Record<AssetType, string> = {
  fd: "Fixed Deposits",
  rd: "Recurring Deposits",
  stock: "Stocks",
  bond: "Bonds",
  mf: "Mutual Funds",
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

export interface StockInput {
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
  name: string;
  isin: string | null;
  issuer: string;
  bond_type: BondType;
  platform: string | null;
  quantity: number;
  face_value: number;
  purchase_price: number;
  purchase_date: string;
  ytm: number;
  maturity_date: string;
  notes: string | null;
}

export interface MutualFundInput {
  scheme_name: string;
  platform: string | null;
  category: MFCategory;
  units: number;
  avg_nav: number;
  purchase_date: string;
  notes: string | null;
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
export type Bond = Omit<BondInput, "face_value"> &
  RecordFields & { face_value: number | null };
export type MutualFund = MutualFundInput & RecordFields;

export type AssetRecord =
  | FixedDeposit
  | RecurringDeposit
  | Stock
  | Bond
  | MutualFund;

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
export type StockItem = Stock & ComputedFields;
export type BondItem = Bond & ComputedFields;
export type MutualFundItem = MutualFund & ComputedFields;

export type HoldingRow =
  | FixedDepositItem
  | RecurringDepositItem
  | StockItem
  | BondItem
  | MutualFundItem;

export interface FacetValue {
  value: string;
  count: number;
}

export interface HoldingsSummary {
  count: number;
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
}

import { formatINRWhole } from "./format";
import { CESS_RATE, leftToPay } from "./tax";

export type CapitalGainsTerm = "short" | "long" | "flat";

export type CapitalGainsBucketKey =
  | "equity_st"
  | "equity_st_old"
  | "equity_lt"
  | "equity_lt_old"
  | "other_lt"
  | "slab"
  | "crypto";

export type CapitalGainsFlag =
  | "grandfathering"
  | "no_purchase_date"
  | "guessed_class"
  | "old_rules"
  | "multi_asset"
  | "estimated";

export type CapitalGainsSource = "sale" | "maturity" | "planned_sale";

export interface CapitalGainsFyOption {
  start_year: number;
  label: string;
  is_current: boolean;
}

export interface CapitalGainsSummary {
  short_term_net: number;
  long_term_net: number;
  losses_set_off: number;
  unused_losses: number;
  exemption_used: number;
  fixed_rate_tax: number;
  slab_gains: number;
  sales_count: number;
}

export interface CapitalGainsBucket {
  key: CapitalGainsBucketKey;
  label: string;
  term: CapitalGainsTerm;
  rate: number | null;
  gains: number;
  losses: number;
  net: number;
  set_off: number;
  exemption: number;
  taxable: number;
  tax: number | null;
}

export interface CapitalGainsLot {
  bought_on: string | null;
  quantity: number | null;
  cost: number;
  proceeds: number;
  gain: number;
  days_held: number | null;
  term: CapitalGainsTerm | null;
  bucket: string | null;
}

export interface CapitalGainsSale {
  exit_id: number | null;
  source: CapitalGainsSource;
  estimated: boolean;
  asset_type: "stock" | "bond" | "mf" | "gold" | "other";
  holding_id: number;
  name: string;
  sold_on: string;
  proceeds: number;
  cost: number;
  gain: number;
  flags: CapitalGainsFlag[];
  lots: CapitalGainsLot[];
}

export interface CapitalGainsTaxFreeItem {
  exit_id: number | null;
  holding_id: number;
  name: string;
  estimated: boolean;
  settled_on: string;
  amount: number;
  cost: number;
  gain: number;
}

export interface CapitalGainsBondInterest {
  interest_to_date: number;
  interest_projected: number;
  tds_estimate: number;
  holdings_count: number;
}

export interface CapitalGains {
  fy: string;
  fy_start: string;
  fy_end: string;
  as_of: string;
  is_current: boolean;
  available_fys: CapitalGainsFyOption[];
  summary: CapitalGainsSummary;
  buckets: CapitalGainsBucket[];
  sales: CapitalGainsSale[];
  expected: CapitalGainsSale[];
  expected_gain: number;
  bond_interest: CapitalGainsBondInterest | null;
  tax_free: { total: number; items: CapitalGainsTaxFreeItem[] };
  excluded: { bonds_no_face: number; no_purchase_date: number; old_rules: number };
}

export const CAPITAL_GAINS_PATH = "/analytics/capital-gains";

/** Request path for one financial year (by start year); no year means the API's current year. */
export function capitalGainsPath(fyStartYear?: number | null): string {
  return fyStartYear == null ? CAPITAL_GAINS_PATH : `${CAPITAL_GAINS_PATH}?fy=${fyStartYear}`;
}

/**
 * Estimated tax on the year's gains: fixed-rate tax plus slab gains at the chosen slab,
 * plus 4% cess, whole rupees. Null while slab gains exist but no slab is chosen.
 */
export function estimatedTax(
  summary: Pick<CapitalGainsSummary, "fixed_rate_tax" | "slab_gains">,
  slabPct: number | null,
): number | null {
  const slabGains = summary.slab_gains > 0 ? summary.slab_gains : 0;
  if (slabGains > 0 && slabPct === null) return null;
  const slabTax = slabGains > 0 ? slabGains * ((slabPct ?? 0) / 100) : 0;
  const base = Math.max(summary.fixed_rate_tax, 0) + slabTax;
  return Math.round(base * (1 + CESS_RATE));
}

function yearsMonthsText(months: number): string {
  const y = Math.floor(months / 12);
  const m = months % 12;
  const parts: string[] = [];
  if (y > 0) parts.push(`${y} ${y === 1 ? "yr" : "yrs"}`);
  if (m > 0) parts.push(`${m} mo`);
  return parts.join(" ");
}

function daysText(days: number): string {
  return `${days} ${days === 1 ? "day" : "days"}`;
}

function parseYmd(s: string): [number, number, number] | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null;
}

/** Holding period between two YYYY-MM-DD dates, in whole calendar months (days when under one). */
export function heldBetween(bought: string | null, sold: string): string {
  if (!bought) return "Unknown";
  const a = parseYmd(bought);
  const b = parseYmd(sold);
  if (!a || !b) return "Unknown";
  const days = Math.round((Date.UTC(b[0], b[1] - 1, b[2]) - Date.UTC(a[0], a[1] - 1, a[2])) / 86400000);
  if (days < 0) return "Unknown";
  const months = (b[0] - a[0]) * 12 + (b[1] - a[1]) - (b[2] < a[2] ? 1 : 0);
  if (months < 1) return daysText(days);
  return yearsMonthsText(months);
}

export function termText(term: CapitalGainsTerm | null): string {
  if (term === "short") return "Short Term";
  if (term === "long") return "Long Term";
  if (term === "flat") return "Flat 30%";
  return "Not Counted";
}

/** One term label for a sale, from its lots. */
export function saleTermSummary(sale: Pick<CapitalGainsSale, "lots">): string {
  const counted = sale.lots.filter((l) => l.bucket !== null && l.term !== null);
  if (counted.length === 0) return "Not Counted";
  const terms = new Set(counted.map((l) => l.term));
  if (terms.size === 1) return termText(counted[0].term);
  if (terms.has("short") && terms.has("long")) return "Part Short, Part Long Term";
  return termText(counted[0].term);
}

const FLAG_TEXT: Record<CapitalGainsFlag, string> = {
  grandfathering:
    "Bought before 1 Feb 2018: your cost may be higher under the 31 Jan 2018 price rule. Not applied here.",
  no_purchase_date: "No purchase date, so short or long term can't be told. Not counted in the tax.",
  guessed_class: "Tax type guessed from the name. Check it.",
  old_rules: "Sold before 23 Jul 2024, under the old rules with indexation. Not counted in the tax.",
  multi_asset:
    "Multi-asset fund: its tax depends on its equity share. Treated as non-equity.",
  estimated: "Estimated: counted at face value on the repayment date.",
};

export function flagText(code: CapitalGainsFlag): string {
  return FLAG_TEXT[code];
}

export function sourceText(source: CapitalGainsSource): string {
  if (source === "maturity") return "Repaid At Maturity";
  if (source === "planned_sale") return "Planned Sale";
  return "Sold";
}

/**
 * Bond interest left to pay at the slab, from the same figures as the Interest & TDS tab
 * (projected interest, estimated TDS, tax at slab with cess). Null without a slab;
 * negative means a refund is due.
 */
export function bondInterestLeftToPay(
  bi: Pick<CapitalGainsBondInterest, "interest_projected" | "tds_estimate">,
  slabPct: number | null,
): number | null {
  return slabPct === null ? null : leftToPay(bi.interest_projected, bi.tds_estimate, slabPct);
}

/** "Your Slab", or the rate: "20%", "12.5%". */
export function rateText(bucket: Pick<CapitalGainsBucket, "rate">): string {
  return bucket.rate === null ? "Your Slab" : `${bucket.rate}%`;
}

/** Equity long-term exemption per year: ₹1.25 lakh from FY 2024-25, ₹1 lakh before. */
export function exemptionLimitText(fyStartYear: number): string {
  return fyStartYear >= 2024 ? "₹1.25 lakh" : "₹1 lakh";
}

/** Plain-words notes for a bucket: a short line, and the full reason for the info popover. */
export function bucketNotes(
  bucket: Pick<CapitalGainsBucket, "set_off" | "exemption">,
  fyStartYear: number,
): { short: string; long: string } {
  const short: string[] = [];
  const long: string[] = [];
  if (bucket.exemption > 0) {
    short.push(`${formatINRWhole(bucket.exemption)} tax-free`);
    long.push(
      `${formatINRWhole(bucket.exemption)} of this is tax-free: under Section 112A, the first ${exemptionLimitText(fyStartYear)} of equity long-term gains each year is exempt, in both the old and new tax regimes.`,
    );
  }
  if (bucket.set_off > 0) {
    short.push(`${formatINRWhole(bucket.set_off)} offset by losses`);
    long.push(
      `${formatINRWhole(bucket.set_off)} of this gain was offset by losses from other sales this year, so it is not taxed.`,
    );
  }
  return { short: short.join(" · "), long: long.join(" ") };
}

/** Plain-sentence notes under the page. */
export function footnotes(
  data: Pick<CapitalGains, "excluded" | "tax_free" | "sales" | "expected">,
): string[] {
  const out = [
    "Losses are set off within the year only; carrying them forward isn't tracked.",
    "Surcharge and the 87A rebate are ignored; 4% cess is added.",
  ];
  const { bonds_no_face: noFace, no_purchase_date: noDate, old_rules: old } = data.excluded;
  if (noFace > 0) {
    out.push(
      `${noFace} ${noFace === 1 ? "bond without a face value isn't" : "bonds without a face value aren't"} included.`,
    );
  }
  if ([...data.sales, ...data.expected].some((x) => x.source !== "sale")) {
    out.push(
      "Bonds are counted at face value when they're repaid or sold as planned, whether or not you've settled them. Bonds that repay principal in instalments are treated as repaid in full at maturity.",
    );
  }
  if (noDate > 0) {
    out.push(`${noDate} ${noDate === 1 ? "sale isn't" : "sales aren't"} counted: no purchase date.`);
  }
  if (old > 0) {
    out.push(
      `${old} ${old === 1 ? "sale isn't" : "sales aren't"} counted: sold before 23 Jul 2024, under the old rules.`,
    );
  }
  if (data.tax_free.total > 0) {
    out.push(
      `${formatINRWhole(data.tax_free.total)} from Sovereign Gold Bonds redeemed at maturity is tax-free.`,
    );
  }
  return out;
}

import { formatINRWhole } from "./format";
import type { CapitalGainsFyOption, CapitalGainsTerm } from "./capital-gains";

export type UnrealisedFlag =
  | "grandfathering"
  | "no_purchase_date"
  | "guessed_class"
  | "old_rules"
  | "multi_asset"
  | "estimated"
  | "single_lot_average"
  | "single_lot_fallback";

export type UnrealisedAssetType = "stock" | "bond" | "mf" | "gold" | "other";

export interface UnrealisedSummary {
  total_gain: number;
  short_term_net: number;
  long_term_net: number;
  uncounted_lots: number;
}

export interface UnrealisedBucket {
  key: string;
  label: string;
  term: CapitalGainsTerm;
  rate: number | null;
  gains: number;
  losses: number;
  net: number;
}

export interface UnrealisedLot {
  bought_on: string | null;
  quantity: number | null;
  cost: number;
  value: number;
  gain: number;
  days_held: number | null;
  term: CapitalGainsTerm | null;
  long_term_on: string | null;
  days_to_long_term: number | null;
  bucket: string | null;
  bucket_after: string | null;
}

export interface UnrealisedHolding {
  asset_type: UnrealisedAssetType;
  holding_id: number;
  name: string;
  cost: number;
  value: number;
  gain: number;
  flags: UnrealisedFlag[];
  lots: UnrealisedLot[];
}

export interface TurningLot {
  asset_type: UnrealisedAssetType;
  holding_id: number;
  name: string;
  bought_on: string | null;
  quantity: number | null;
  gain: number;
  bucket: string | null;
  bucket_after: string | null;
  long_term_on: string;
  days_to_long_term: number;
}

export interface LossLot {
  asset_type: UnrealisedAssetType;
  holding_id: number;
  name: string;
  bought_on: string | null;
  quantity: number | null;
  gain: number;
  bucket: string | null;
  term: CapitalGainsTerm | null;
}

export interface UnrealisedHarvest {
  exemption_limit: number;
  exemption_used: number;
  exemption_room: number;
  unrealised_equity_lt_gain: number;
  turning_long_term: TurningLot[];
  loss_lots: LossLot[];
}

export interface UnrealisedExcluded {
  at_cost: number;
  no_invested_amount: number;
  bonds_no_face: number;
  no_purchase_date: number;
}

export interface Unrealised {
  fy: string;
  fy_start: string;
  fy_end: string;
  as_of: string;
  is_current: boolean;
  available_fys: CapitalGainsFyOption[];
  summary: UnrealisedSummary;
  buckets: UnrealisedBucket[];
  harvest: UnrealisedHarvest;
  holdings: UnrealisedHolding[];
  excluded: UnrealisedExcluded;
}

export const UNREALISED_PATH = "/analytics/unrealised";
export const LIST_PAGE = 5;

/** Request path for one financial year (by start year); no year means the API's current year. */
export function unrealisedPath(fyStartYear?: number | null): string {
  return fyStartYear == null ? UNREALISED_PATH : `${UNREALISED_PATH}?fy=${fyStartYear}`;
}

/** Share of each side of the short/long split bar, by size regardless of sign. */
export function splitPercents(short: number, long: number): { short: number; long: number } {
  const a = Math.abs(short);
  const b = Math.abs(long);
  const total = a + b;
  if (total === 0) return { short: 0, long: 0 };
  return { short: (a / total) * 100, long: (b / total) * 100 };
}

/** Exemption used as a share of the limit, kept between 0 and 100. */
export function progressPercent(used: number, limit: number): number {
  if (limit <= 0) return 0;
  return Math.min(100, Math.max(0, (used / limit) * 100));
}

/** First `LIST_PAGE` items, or all of them once expanded. */
export function visibleItems<T>(items: T[], expanded: boolean, size: number = LIST_PAGE): T[] {
  return expanded ? items : items.slice(0, size);
}

export function hasMore<T>(items: T[], size: number = LIST_PAGE): boolean {
  return items.length > size;
}

export function daysLeftText(days: number): string {
  if (days <= 0) return "Today";
  return `${days} ${days === 1 ? "day" : "days"} left`;
}

const BUCKET_LABELS: Record<string, string> = {
  equity_st: "Equity, Short Term",
  equity_st_old: "Equity, Short Term (Before 23 Jul 2024)",
  equity_lt: "Equity, Long Term",
  equity_lt_old: "Equity, Long Term (Before 23 Jul 2024)",
  other_lt: "Other Assets, Long Term",
  slab: "Taxed At Your Slab",
  crypto: "Crypto",
};

export function bucketLabel(key: string | null): string {
  if (key === null) return "Not Counted";
  return BUCKET_LABELS[key] ?? key;
}

/** Rate shown beside a bucket: "20%", "12.5%" or "Your Slab". */
export function bucketRateText(rate: number | null): string {
  return rate === null ? "Your Slab" : `${rate}%`;
}

/** Headline subline: "short term ₹x · long term ₹y". */
export function splitSubline(s: Pick<UnrealisedSummary, "short_term_net" | "long_term_net">): string {
  return `short term ${formatINRWhole(s.short_term_net)} · long term ${formatINRWhole(s.long_term_net)}`;
}

/** Fact sentence for the tax-free room, no advice wording. */
export function roomSentence(room: number): string {
  return `${formatINRWhole(room)} of long-term equity gains can be booked tax-free this year.`;
}

const FLAG_TEXT: Record<UnrealisedFlag, string> = {
  grandfathering:
    "Bought before 1 Feb 2018: your cost may be higher under the 31 Jan 2018 price rule. Not applied here.",
  no_purchase_date: "Some lots have no purchase date, so short or long term can't be told. They are not counted.",
  guessed_class: "Tax type guessed from the name for some holdings. Check it.",
  old_rules: "Some lots were bought under rules that no longer apply and are not counted.",
  multi_asset: "Multi-asset funds are taxed by their equity share. They are treated as non-equity.",
  estimated: "Some figures are estimated.",
  single_lot_average:
    "A stock is shown as one lot at its average price, not its real purchase lots, so its short and long term split is approximate.",
  single_lot_fallback:
    "A fund whose transactions don't add up to its units is shown as one lot.",
};

export function unrealisedFlagText(flag: UnrealisedFlag): string {
  return FLAG_TEXT[flag];
}

/** One sentence per distinct flag across the holdings, in a fixed order. */
export function flagSentences(holdings: Pick<UnrealisedHolding, "flags">[]): string[] {
  const seen = new Set<UnrealisedFlag>();
  for (const h of holdings) for (const f of h.flags) seen.add(f);
  return (Object.keys(FLAG_TEXT) as UnrealisedFlag[]).filter((f) => seen.has(f)).map((f) => FLAG_TEXT[f]);
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** Notes for what the figures leave out. */
export function excludedNotes(e: UnrealisedExcluded, uncountedLots: number = 0): string[] {
  const out: string[] = [];
  if (e.at_cost > 0) {
    out.push(`${plural(e.at_cost, "holding is", "holdings are")} valued at cost because there is no price yet.`);
  }
  if (e.bonds_no_face > 0) {
    out.push(`${plural(e.bonds_no_face, "bond without a face value isn't", "bonds without a face value aren't")} included.`);
  }
  if (e.no_purchase_date > 0) {
    out.push(`${plural(e.no_purchase_date, "holding has", "holdings have")} no purchase date, so ${e.no_purchase_date === 1 ? "its" : "their"} term can't be told.`);
  }
  if (e.no_invested_amount > 0) {
    out.push(`${plural(e.no_invested_amount, "Other holding has", "Other holdings have")} no amount invested, so no gain is shown.`);
  }
  if (uncountedLots > 0) {
    out.push(`${plural(uncountedLots, "lot isn't", "lots aren't")} counted in the totals.`);
  }
  return out;
}

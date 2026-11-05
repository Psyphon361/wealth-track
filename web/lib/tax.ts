import { formatINR, formatINRWhole } from "./format";
import type { AnalyticsTax, TaxClassRow, TaxFyOption, TaxHolding, TaxPayer } from "./types";

/** "2026-27" -> "2026–27" (en dash). */
export function fyDisplay(label: string): string {
  return label.replace("-", "–");
}

/** Select label for a financial year, e.g. "FY 2026–27". */
export function fyOptionLabel(opt: TaxFyOption): string {
  return `FY ${fyDisplay(opt.label)}`;
}

/** Slab Select label: "0% (no tax)" for zero, otherwise "25%". */
export function slabOptionLabel(slab: number): string {
  return slab === 0 ? "0% (no tax)" : `${slab}%`;
}

/** Slab Select trigger text: "25% slab". */
export function slabTriggerLabel(slab: number): string {
  return `${slab}% slab`;
}

/** Card label: "Interest this year, by type", or "Interest in FY 2025–26, by type" for a past year. */
export function taxCardLabel(tax: Pick<AnalyticsTax, "is_current" | "fy">): string {
  return tax.is_current
    ? "Interest this year, by type"
    : `Interest in FY ${fyDisplay(tax.fy)}, by type`;
}

/** Muted text after a class name: "· 3 deposits", "· 1 bond", or "· estimate" for savings. */
export function classCountText(row: TaxClassRow): string {
  if (row.type === "savings") return " · estimate";
  const n = row.holdings_count;
  const noun = row.type === "bond" ? "bond" : "deposit";
  return ` · ${n} ${noun}${n === 1 ? "" : "s"}`;
}

/**
 * Filled share (0-100) of a class bar. Current year: how much of the year's interest is
 * already received. Past year: this class's share of all classes' interest.
 */
export function classBarPercent(
  row: TaxClassRow,
  isCurrent: boolean,
  allProjected: number,
): number {
  const denom = isCurrent ? row.interest_projected : allProjected;
  const num = isCurrent ? row.interest_to_date : row.interest_projected;
  if (!(denom > 0) || !(num > 0)) return 0;
  return Math.min(100, Math.max(0, (num / denom) * 100));
}

/** Sum of every class's projected interest for the year (the past-year bar denominator). */
export function allClassesProjected(rows: TaxClassRow[]): number {
  return rows.reduce((s, r) => s + r.interest_projected, 0);
}

/** Line under a class bar: "₹6,783 received · ₹5,148 to come", or "42% of the year's interest". */
export function classProgressText(
  row: TaxClassRow,
  isCurrent: boolean,
  allProjected: number,
): string {
  if (!isCurrent) {
    return `${Math.round(classBarPercent(row, false, allProjected))}% of the year's interest`;
  }
  const verb = row.type === "savings" ? "so far" : "received";
  const toCome = Math.max(row.interest_projected - row.interest_to_date, 0);
  return `${formatINRWhole(row.interest_to_date)} ${verb} · ${formatINRWhole(toCome)} to come`;
}

/** Plain-words TDS pill of a class row. `warn` is true when TDS will be cut. */
export function classTdsPill(
  row: TaxClassRow,
  payers: ClassPayer[],
): { text: string; warn: boolean } {
  if (row.type === "savings") return { text: "Banks don't cut TDS on savings", warn: false };
  const tds = row.tds_estimate;
  if (row.type === "bond") {
    return tds > 0
      ? { text: `${formatINRWhole(tds)} TDS · 10% of each coupon`, warn: true }
      : { text: "No TDS on these bonds", warn: false };
  }
  if (tds > 0) {
    const crossers = payers.filter((p) => p.payer.crosses);
    const n = crossers.length;
    if (n === 0) return { text: `${formatINRWhole(tds)} TDS`, warn: true };
    const unit = crossers.every((p) => p.payer.kind === "bank") ? "bank" : "payer";
    return {
      text: `${formatINRWhole(tds)} TDS · over the limit at ${n} ${unit}${n === 1 ? "" : "s"}`,
      warn: true,
    };
  }
  if (payers.length > 0 && payers.every((p) => p.payer.kind === "bank")) {
    const limit = payers.find((p) => p.payer.threshold !== null)?.payer.threshold ?? 50000;
    return { text: `No TDS · under ${formatINRWhole(limit)} per bank`, warn: false };
  }
  return { text: "No TDS · each payer under its limit", warn: false };
}

/** Coupons not yet paid across one payer's holdings in the year. */
export function couponsLeft(payer: ClassPayer): number {
  let n = 0;
  for (const h of payer.holdings) {
    for (const p of h.payments ?? []) if (!p.paid) n += 1;
  }
  return n;
}

/** "1 coupon left" / "2 coupons left". */
export function couponsLeftText(n: number): string {
  return `${n} ${n === 1 ? "coupon" : "coupons"} left`;
}

/** Muted tail after an amount: " · ₹475 TDS" or " · no TDS". `exact` keeps the paise. */
export function tdsSuffix(tds: number, exact = false): string {
  if (!(tds > 0)) return " · no TDS";
  return ` · ${exact ? formatINR(tds) : formatINRWhole(tds)} TDS`;
}

/** One payer inside an asset class, with the figures of that class's holdings only. */
export interface ClassPayer {
  key: string;
  name: string;
  payer: TaxPayer;
  holdings: TaxHolding[];
  interest_to_date: number;
  interest_projected: number;
  tds_estimate: number;
}

/** Payers of one asset class (FD/RD: banks and companies; bonds: bond issuers), biggest first. */
export function classPayers(payers: TaxPayer[], type: TaxClassRow["type"]): ClassPayer[] {
  if (type === "savings") return [];
  const out: ClassPayer[] = [];
  for (const p of payers) {
    const fits = type === "bond" ? p.kind === "bond" : p.kind !== "bond";
    if (!fits) continue;
    const holdings = p.holdings
      .filter((h) => h.type === type)
      .sort((a, b) => b.interest_projected - a.interest_projected || a.name.localeCompare(b.name));
    if (holdings.length === 0) continue;
    out.push({
      key: p.key,
      name: p.name,
      payer: p,
      holdings,
      interest_to_date: holdings.reduce((s, h) => s + h.interest_to_date, 0),
      interest_projected: holdings.reduce((s, h) => s + h.interest_projected, 0),
      tds_estimate: holdings.reduce((s, h) => s + h.tds_estimate, 0),
    });
  }
  return out.sort(
    (a, b) => b.interest_projected - a.interest_projected || a.name.localeCompare(b.name),
  );
}

/** Marker beside a payer: over its TDS limit, or within 20% of it. Otherwise null. */
export function tdsLimitMarker(p: TaxPayer): { text: string; over: boolean } | null {
  if (p.tds_rule !== "threshold" || p.threshold === null || !(p.threshold > 0)) return null;
  if (p.crosses) return { text: "Over TDS limit", over: true };
  const left = p.threshold - p.interest_projected;
  if (left <= p.threshold * 0.2) {
    return { text: `${formatINRWhole(Math.max(left, 0))} to TDS limit`, over: false };
  }
  return null;
}

/** Footnote for the savings-interest estimate, including the 80TTA note. */
export function savingsSentence(savings: NonNullable<AnalyticsTax["savings"]>): string {
  const n = savings.accounts;
  return `Savings interest is about ${formatINRWhole(savings.interest_estimate)} across ${n} ${n === 1 ? "account" : "accounts"}. It's taxable, with no TDS. Under the old regime up to ₹10,000 of it is deductible (80TTA); the new regime has no such deduction.`;
}

/** Footnote for bonds left out because the coupon details are missing. */
export function bondsNote(n: number): string {
  return `${n} ${n === 1 ? "bond" : "bonds"} without coupon details ${n === 1 ? "isn't" : "aren't"} included.`;
}

export const TAX_SLAB_KEY = "wt.analytics.taxSlab";
export const SLAB_OPTIONS = [0, 5, 10, 15, 20, 25, 30] as const;
export const CESS_RATE = 0.04;

/** A stored slab string -> a valid slab percent, or null (anything else is ignored). */
export function parseSlab(raw: string | null): number | null {
  if (raw === null) return null;
  const n = Number(raw);
  return (SLAB_OPTIONS as readonly number[]).includes(n) && raw.trim() !== "" ? n : null;
}

/** Tax on interest at a slab (percent) including 4% cess, whole rupees. */
export function taxOnInterest(taxable: number, slabPct: number): number {
  if (!(taxable > 0) || !(slabPct > 0)) return 0;
  return Math.round(taxable * (slabPct / 100) * (1 + CESS_RATE));
}

/** Tax at the slab minus TDS already deducted: positive = left to pay, negative = refund. */
export function leftToPay(taxable: number, tds: number, slabPct: number): number {
  return taxOnInterest(taxable, slabPct) - tds;
}

/** Label for the third summary figure: a refund reads "Refund due", everything else "Left to pay". */
export function leftToPayLabel(left: number | null): string {
  return left !== null && left < 0 ? "Refund due" : "Left to pay";
}

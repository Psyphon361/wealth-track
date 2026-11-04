import { formatINRWhole } from "./format";
import type { AnalyticsTax, TaxFyOption, TaxPayer } from "./types";

/** "2026-27" -> "2026–27" (en dash). */
export function fyDisplay(label: string): string {
  return label.replace("-", "–");
}

/** Title Case Select label for a financial year. */
export function fyOptionLabel(opt: TaxFyOption): string {
  return `${opt.is_current ? "This FY" : "Last FY"} ${fyDisplay(opt.label)}`;
}

/** Share of the threshold reached by the year's interest, 0 to 100. */
export function barShare(projected: number, threshold: number): number {
  if (!(threshold > 0) || !(projected > 0)) return 0;
  return Math.min(100, (projected / threshold) * 100);
}

/** "SBI", "SBI and HDFC Bank", "SBI, HDFC Bank and Axis Bank". */
export function joinNames(names: string[]): string {
  if (names.length <= 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/** Subline under the "Interest this year" headline. */
export function interestSubline(tax: AnalyticsTax): string {
  if (!tax.is_current) return "Full year";
  return `${formatINRWhole(tax.totals.interest_to_date)} so far · about ${formatINRWhole(tax.totals.interest_projected)} by 31 Mar`;
}

/** Plain sentence for the "TDS to expect" card. */
export function tdsSentence(payers: TaxPayer[], isCurrent: boolean): string {
  const crossing = payers.filter((p) => p.crosses);
  const hasIssuer = payers.some((p) => p.kind === "bond");
  const who = hasIssuer ? "bank or issuer" : "bank";
  if (crossing.length === 0) {
    return isCurrent
      ? `No ${who} crosses its TDS limit this year.`
      : `No ${who} crossed its TDS limit that year.`;
  }
  const total = crossing.reduce((sum, p) => sum + p.tds_estimate, 0);
  const verb = isCurrent ? "will deduct" : "deducted";
  return `${joinNames(crossing.map((p) => p.name))} ${verb} about ${formatINRWhole(total)} in TDS.`;
}

/** Row hint under a payer name: limit and where it stands. */
export function payerHint(p: TaxPayer): string {
  if (p.threshold === null) return "No TDS";
  const limit = formatINRWhole(p.threshold);
  return p.crosses ? `Over the ${limit} limit` : `Limit ${limit}`;
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

/** Share of the taxable part in the taxable / tax-free bar, 0 to 100. */
export function taxableShare(taxable: number, taxFree: number): number {
  const total = taxable + taxFree;
  if (!(total > 0)) return 0;
  return (Math.max(taxable, 0) / total) * 100;
}

/** Sentence for the "Tax on your interest" card once a slab is chosen. */
export function slabSentence(
  taxable: number,
  tds: number,
  slabPct: number,
  isCurrent: boolean,
): string {
  const tdsWord = isCurrent ? "deduct" : "deducted";
  if (slabPct === 0) {
    const base = "No tax on this interest at 0%.";
    if (!(tds > 0)) return base;
    return `${base} Banks and issuers ${tdsWord} ${formatINRWhole(tds)} in TDS, which you can claim back when you file.`;
  }
  const tax = taxOnInterest(taxable, slabPct);
  const head = `At ${slabPct}%, tax on ${formatINRWhole(taxable)} of taxable interest is about ${formatINRWhole(tax)}.`;
  const tdsPart = tds > 0 ? `Banks and issuers ${tdsWord} ${formatINRWhole(tds)}` : "No TDS is taken";
  const diff = tax - tds;
  if (diff > 0) return `${head} ${tdsPart}, so you'd pay about ${formatINRWhole(diff)} more when you file.`;
  if (diff < 0) return `${head} ${tdsPart}, so you'd get about ${formatINRWhole(-diff)} back.`;
  return `${head} ${tdsPart}, which covers it.`;
}

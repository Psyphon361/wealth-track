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
  if (crossing.length === 0) {
    return isCurrent
      ? "No bank crosses its TDS limit this year."
      : "No bank crossed its TDS limit that year.";
  }
  const total = crossing.reduce((sum, p) => sum + p.tds_estimate, 0);
  const verb = isCurrent ? "will deduct" : "deducted";
  return `${joinNames(crossing.map((p) => p.name))} ${verb} about ${formatINRWhole(total)} in TDS.`;
}

/** Row hint under a payer name: limit and where it stands. */
export function payerHint(p: TaxPayer): string {
  const limit = formatINRWhole(p.threshold);
  return p.crosses ? `Over the ${limit} limit` : `Limit ${limit}`;
}

/** Footnote line for the savings-interest estimate. */
export function savingsSentence(savings: NonNullable<AnalyticsTax["savings"]>): string {
  const n = savings.accounts;
  return `Savings interest is about ${formatINRWhole(savings.interest_estimate)} across ${n} ${n === 1 ? "account" : "accounts"}. No TDS is taken on it.`;
}

export const SAVINGS_80TTA_NOTE =
  "Savings interest is taxable. Under the old regime up to ₹10,000 of it is deductible (80TTA); the new regime has no such deduction.";

export const BONDS_NOTE = "Bonds aren't included yet.";

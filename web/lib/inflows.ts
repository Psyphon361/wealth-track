import { ANALYTICS_INFLOWS_PATH } from "./analytics";

export type InflowKind = "coupon" | "interest_payout" | "maturity" | "redemption";

export interface InflowItem {
  date: string;
  type: string;
  id: number;
  name: string;
  kind: InflowKind;
  interest: number;
  principal: number;
}

export interface InflowMonth {
  /** "2026-12" */
  month: string;
  interest: number;
  principal: number;
  items: InflowItem[];
}

export interface AnalyticsInflows {
  as_of: string;
  months: InflowMonth[];
  totals: { interest: number; principal: number };
  types: string[];
}

export type InflowMonthsCount = 12 | 24;

const TYPE_LABELS: Record<string, string> = {
  fd: "Fixed Deposits",
  rd: "Recurring Deposits",
  bond: "Bonds",
  stock: "Stocks",
  mf: "Mutual Funds",
  nps: "NPS",
  gold: "Gold & Silver",
  cash: "Cash & Savings",
  pf: "EPF & PPF",
  other: "Other",
};

const KIND_LABELS: Record<InflowKind, string> = {
  coupon: "Coupon",
  interest_payout: "Interest Payout",
  maturity: "Maturity",
  redemption: "Redemption",
};

export function inflowTypeLabel(slug: string): string {
  return TYPE_LABELS[slug] ?? slug.charAt(0).toUpperCase() + slug.slice(1);
}

export function inflowKindLabel(kind: InflowKind): string {
  return KIND_LABELS[kind] ?? kind;
}

export function inflowsPath(months: InflowMonthsCount): string {
  return `${ANALYTICS_INFLOWS_PATH}?months=${months}`;
}

export function itemTotal(item: InflowItem): number {
  return item.interest + item.principal;
}

/**
 * Applies the card filters to the fetched months. Month totals are recomputed from the kept items.
 * "Interest only" drops the principal part of each item and any item left with no interest.
 */
export function filterInflows(
  months: InflowMonth[],
  type: string,
  interestOnly: boolean,
): InflowMonth[] {
  return months.map((m) => {
    const items: InflowItem[] = [];
    for (const it of m.items) {
      if (type !== "all" && it.type !== type) continue;
      const next = interestOnly ? { ...it, principal: 0 } : it;
      if (itemTotal(next) <= 0) continue;
      items.push(next);
    }
    return {
      month: m.month,
      interest: items.reduce((s, it) => s + it.interest, 0),
      principal: items.reduce((s, it) => s + it.principal, 0),
      items,
    };
  });
}

export function inflowTotals(months: InflowMonth[]): { interest: number; principal: number } {
  return {
    interest: months.reduce((s, m) => s + m.interest, 0),
    principal: months.reduce((s, m) => s + m.principal, 0),
  };
}

export interface InflowColumn {
  month: string;
  /** heights as percent of the chart height; the tallest month fills it */
  interestPct: number;
  principalPct: number;
}

export function inflowColumns(months: InflowMonth[]): InflowColumn[] {
  const max = Math.max(0, ...months.map((m) => m.interest + m.principal));
  return months.map((m) => ({
    month: m.month,
    interestPct: max > 0 ? (m.interest / max) * 100 : 0,
    principalPct: max > 0 ? (m.principal / max) * 100 : 0,
  }));
}

/** The month to show when nothing is hovered: the first month with money coming in, else the first. */
export function defaultMonth(months: InflowMonth[]): string | null {
  const first = months.find((m) => m.interest + m.principal > 0) ?? months[0];
  return first?.month ?? null;
}

/** Items of one month, soonest first. */
export function sortedItems(month: InflowMonth | undefined): InflowItem[] {
  if (!month) return [];
  return [...month.items].sort((a, b) => a.date.localeCompare(b.date) || a.id - b.id);
}

export function inflowHref(item: InflowItem): string {
  return `/portfolio/${item.type}/${item.id}`;
}

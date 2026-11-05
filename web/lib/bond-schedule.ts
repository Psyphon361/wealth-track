import { formatDate, formatINRWhole } from "./format";
import type { BondFyRow, BondScheduleBond } from "./types";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAY_MS = 86_400_000;

export const BOND_SCHEDULE_PATH = "/analytics/bond-schedule";
export const ALL_BONDS = "all";

/** "2026-04-18" -> whole days since the epoch (UTC, no timezone shift). */
export function dayNum(iso: string): number {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return Math.round(Date.UTC(y, m - 1, d) / DAY_MS);
}

/** Whole days from `asOf` to `iso` (negative when in the past). */
export function daysUntil(iso: string, asOf: string): number {
  return dayNum(iso) - dayNum(asOf);
}

/** "in 3 days", "tomorrow", "today". */
export function daysText(days: number): string {
  if (days <= 0) return "today";
  if (days === 1) return "tomorrow";
  return `in ${days} days`;
}

/** "2027-28" -> "FY 27–28". */
export function fyShort(fy: string): string {
  const [a, b] = fy.split("-");
  return `FY ${a.slice(-2)}–${b}`;
}

/** Select option label: "<name> · <n> units · bought <date>". */
export function optionLabel(b: BondScheduleBond): string {
  const units = `${b.quantity.toLocaleString("en-IN")} ${b.quantity === 1 ? "unit" : "units"}`;
  return `${b.name} · ${units} · bought ${formatDate(b.purchase_date)}`;
}

/** Second line of a Select option: "<n> units · bought <date>". */
export function optionDetail(b: BondScheduleBond): string {
  const units = `${b.quantity.toLocaleString("en-IN")} ${b.quantity === 1 ? "unit" : "units"}`;
  return `${units} · bought ${formatDate(b.purchase_date)}`;
}

/** The bonds picked in the Select: one id, or all of them. Unknown ids fall back to all. */
export function selectBonds(bonds: BondScheduleBond[], sel: string): BondScheduleBond[] {
  if (sel === ALL_BONDS) return bonds;
  const hit = bonds.filter((b) => String(b.id) === sel);
  return hit.length > 0 ? hit : bonds;
}

export interface Progress {
  received: number;
  total: number;
  pct: number;
}

/** Coupons already paid against all coupons (gross), across the bonds. */
export function couponProgress(bonds: BondScheduleBond[]): Progress {
  let received = 0;
  let total = 0;
  for (const b of bonds) {
    for (const p of b.payments) {
      if (p.kind !== "coupon") continue;
      total += p.gross;
      if (p.paid) received += p.gross;
    }
  }
  return { received, total, pct: total > 0 ? Math.min(100, (received / total) * 100) : 0 };
}

export interface CombinedNext {
  date: string;
  days: number;
  names: string[];
  coupon: number;
  redemption: number;
  tds: number;
  net: number;
}

/** The soonest upcoming date, with every bond paying on that date added together. */
export function combinedNext(bonds: BondScheduleBond[], asOf: string): CombinedNext | null {
  let date: string | null = null;
  for (const b of bonds) {
    const p = b.next_payment;
    if (p && (date === null || p.date < date)) date = p.date;
  }
  if (date === null) return null;
  const out: CombinedNext = {
    date,
    days: daysUntil(date, asOf),
    names: [],
    coupon: 0,
    redemption: 0,
    tds: 0,
    net: 0,
  };
  for (const b of bonds) {
    const p = b.next_payment;
    if (!p || p.date !== date) continue;
    out.names.push(b.name);
    if (p.kind === "redemption") out.redemption += p.gross;
    else out.coupon += p.gross;
    out.tds += p.tds;
    out.net += p.net;
  }
  return out;
}

/** Subline under the headline: coupon less TDS, plus any repayment. */
export function nextSubline(n: CombinedNext, fmt: (v: number) => string): string {
  const parts: string[] = [];
  if (n.coupon > 0) parts.push(`${fmt(n.coupon)} coupon − ${fmt(n.tds)} TDS`);
  if (n.redemption > 0) parts.push(`${fmt(n.redemption)} repaid at maturity`);
  return parts.join(" + ");
}

export interface BucketItem {
  bondId: number;
  name: string;
  date: string;
  kind: "coupon" | "redemption";
  gross: number;
  tds: number;
  net: number;
  paid: boolean;
}

export interface MonthBucket {
  key: string;
  index: number;
  year: number;
  month: number;
  label: string;
  items: BucketItem[];
  /** Coupons only: redemption is drawn as a marker, not a bar. */
  gross: number;
  tds: number;
  net: number;
  redemption: number;
  /** Every payment in the month is paid. */
  paid: boolean;
}

function monthIndex(iso: string): number {
  const [y, m] = iso.split("-").map(Number);
  return y * 12 + (m - 1);
}

/** One bucket per calendar month from the first purchase (or payment) to the last maturity (or payment). */
export function monthBuckets(bonds: BondScheduleBond[]): MonthBucket[] {
  if (bonds.length === 0) return [];
  let lo = Infinity;
  let hi = -Infinity;
  for (const b of bonds) {
    lo = Math.min(lo, monthIndex(b.purchase_date));
    hi = Math.max(hi, monthIndex(b.maturity_date));
    for (const p of b.payments) {
      lo = Math.min(lo, monthIndex(p.date));
      hi = Math.max(hi, monthIndex(p.date));
    }
  }
  const buckets: MonthBucket[] = [];
  for (let i = lo; i <= hi; i++) {
    const year = Math.floor(i / 12);
    const month = i % 12;
    buckets.push({
      key: `${year}-${String(month + 1).padStart(2, "0")}`,
      index: i - lo,
      year,
      month,
      label: MONTHS[month],
      items: [],
      gross: 0,
      tds: 0,
      net: 0,
      redemption: 0,
      paid: true,
    });
  }
  for (const b of bonds) {
    for (const p of b.payments) {
      const bucket = buckets[monthIndex(p.date) - lo];
      bucket.items.push({
        bondId: b.id,
        name: b.name,
        date: p.date,
        kind: p.kind,
        gross: p.gross,
        tds: p.tds,
        net: p.net,
        paid: p.paid,
      });
      if (p.kind === "redemption") bucket.redemption += p.gross;
      else {
        bucket.gross += p.gross;
        bucket.tds += p.tds;
        bucket.net += p.net;
      }
      if (!p.paid) bucket.paid = false;
    }
  }
  for (const bucket of buckets) {
    bucket.items.sort((a, b) => a.date.localeCompare(b.date) || a.name.localeCompare(b.name));
    if (bucket.items.length === 0) bucket.paid = false;
  }
  return buckets;
}

/** Financial year (April to March) a month column belongs to, as "2026-27". */
export function bucketFy(b: MonthBucket): string {
  const start = b.month >= 3 ? b.year : b.year - 1;
  return `${start}-${String((start + 1) % 100).padStart(2, "0")}`;
}

/** The month the next payout falls in, or null. */
export function nextBucketIndex(buckets: MonthBucket[], nextDate: string | null): number | null {
  if (!nextDate) return null;
  const i = buckets.findIndex((b) => b.key === nextDate.slice(0, 7));
  return i < 0 ? null : i;
}

/** Tallest stacked column (net + TDS), at least 1 so heights never divide by zero. */
export function maxColumn(buckets: MonthBucket[]): number {
  return Math.max(1, ...buckets.map((b) => b.net + b.tds));
}

export interface AxisLayout {
  /** More months than fit: the chart scrolls sideways at a fixed slot width. */
  scroll: boolean;
  /** Assumed pixel width of one month column. */
  slot: number;
  /** Label every `step` months. */
  step: number;
}

export const FIT_MAX_MONTHS = 14;
const FIT_WIDTH = 300;
const SCROLL_SLOT = 28;
const LABEL_WIDTH = 30;

/** Column width and label spacing so month labels never overlap. */
export function axisLayout(count: number): AxisLayout {
  const scroll = count > FIT_MAX_MONTHS;
  const slot = scroll ? SCROLL_SLOT : FIT_WIDTH / Math.max(1, count);
  return { scroll, slot, step: Math.max(1, Math.ceil(LABEL_WIDTH / slot)) };
}

export interface AxisLabel {
  index: number;
  month: string;
  /** Set on the first label and whenever the year changes. */
  year: number | null;
}

export function axisLabels(buckets: MonthBucket[], step: number): AxisLabel[] {
  const out: AxisLabel[] = [];
  let lastYear: number | null = null;
  for (const b of buckets) {
    if (b.index % step !== 0) continue;
    out.push({ index: b.index, month: b.label, year: b.year === lastYear ? null : b.year });
    lastYear = b.year;
  }
  return out;
}

export interface FyMarker {
  index: number;
  label: string;
}

/** A financial-year line at each April column (not at the first column). */
export function fyMarkers(buckets: MonthBucket[]): FyMarker[] {
  return buckets
    .filter((b) => b.month === 3 && b.index > 0)
    .map((b) => ({
      index: b.index,
      label: `FY ${String(b.year % 100).padStart(2, "0")}–${String((b.year + 1) % 100).padStart(2, "0")}`,
    }));
}

export const FY_LABEL_MIN_SPACE = 48;

export interface FyPlacement extends FyMarker {
  /** "left": text starts at the line and runs right. "right": text ends at the line. */
  align: "left" | "right";
}

/**
 * Where each FY label goes so none is clipped or overlaps: after the line when 48px fit before the
 * next line or the chart edge, else before it when they fit there, else the label is skipped.
 */
export function fyPlacements(markers: FyMarker[], count: number, slot: number): FyPlacement[] {
  const out: FyPlacement[] = [];
  let lastEnd = 0;
  markers.forEach((m, k) => {
    const x = m.index * slot;
    const nextX = k + 1 < markers.length ? markers[k + 1].index * slot : count * slot;
    if (nextX - x >= FY_LABEL_MIN_SPACE) {
      out.push({ ...m, align: "left" });
      lastEnd = x + FY_LABEL_MIN_SPACE;
    } else if (x - lastEnd >= FY_LABEL_MIN_SPACE) {
      out.push({ ...m, align: "right" });
      lastEnd = x;
    }
  });
  return out;
}

/** Per-year rows summed over the bonds, oldest first. */
export function mergeFy(bonds: BondScheduleBond[]): BondFyRow[] {
  const byFy = new Map<string, BondFyRow>();
  for (const bond of bonds) {
    for (const row of bond.by_fy) {
      const sum = byFy.get(row.fy) ?? { fy: row.fy, coupons: 0, gross: 0, tds: 0, net: 0 };
      sum.coupons += row.coupons;
      sum.gross += row.gross;
      sum.tds += row.tds;
      sum.net += row.net;
      byFy.set(row.fy, sum);
    }
  }
  return [...byFy.values()].sort((a, b) => a.fy.localeCompare(b.fy));
}

/** Each year's share of the total net, in percent. */
export function fyShares(rows: BondFyRow[]): number[] {
  const total = rows.reduce((s, r) => s + r.net, 0);
  return rows.map((r) => (total > 0 ? (r.net / total) * 100 : 0));
}

export interface FyPayoutRow {
  key: string;
  date: string;
  /** Bond name; identical lines of the same bond on the same date are combined. */
  name: string;
  kind: "coupon" | "redemption";
  /** How many identical payments were combined (shown as "×N" when above 1). */
  count: number;
  gross: number;
  tds: number;
  net: number;
  /** Every combined payment is paid. */
  paid: boolean;
}

/**
 * The payouts behind one financial year's row, in date order (coupons before a repayment on the
 * same date). Lines of the same bond, kind and date are combined into one row with summed amounts.
 */
export function fyPayoutRows(bonds: BondScheduleBond[], fy: string): FyPayoutRow[] {
  const groups = new Map<string, FyPayoutRow>();
  for (const b of bonds) {
    for (const p of b.payments) {
      if (p.fy !== fy) continue;
      const key = `${p.date}|${p.kind}|${b.name}`;
      const g = groups.get(key) ?? {
        key,
        date: p.date,
        name: b.name,
        kind: p.kind,
        count: 0,
        gross: 0,
        tds: 0,
        net: 0,
        paid: true,
      };
      g.count += 1;
      g.gross += p.gross;
      g.tds += p.tds;
      g.net += p.net;
      if (!p.paid) g.paid = false;
      groups.set(key, g);
    }
  }
  return [...groups.values()].sort(
    (a, b) =>
      a.date.localeCompare(b.date) ||
      (a.kind === b.kind ? 0 : a.kind === "coupon" ? -1 : 1) ||
      a.name.localeCompare(b.name),
  );
}

/** Payout rows shown at first, and added by each "Show more". */
export const PAYOUT_PAGE = 10;

export interface PayoutPaging {
  /** How many rows to render now. */
  visible: number;
  /** Rows still hidden. */
  left: number;
  /** "Show 10 more · 26 left", "Show 6 more" when the rest fits in one step, or null when none are hidden. */
  moreLabel: string | null;
  /** Everything is shown and the list was longer than one page. */
  canShowLess: boolean;
}

/** Paging of the payout list: `shown` is the count asked for so far (starts at one page). */
export function payoutPaging(total: number, shown: number, page = PAYOUT_PAGE): PayoutPaging {
  const visible = Math.min(total, Math.max(page, shown));
  const left = total - visible;
  const moreLabel =
    left <= 0 ? null : left <= page ? `Show ${left} more` : `Show ${page} more · ${left} left`;
  return { visible, left, moreLabel, canShowLess: left === 0 && total > page };
}

/** The `shown` count after one "Show more" press. */
export function showMoreCount(total: number, shown: number, page = PAYOUT_PAGE): number {
  return Math.min(total, Math.max(page, shown) + page);
}

export interface DateTile {
  day: number;
  month: string;
  /** Two-digit year, "26". */
  year: string;
}

/** "2026-04-18" -> { day: 18, month: "Apr", year: "26" } for the small date tile. */
export function dateTile(iso: string): DateTile {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return { day: d, month: MONTHS[m - 1], year: String(y % 100).padStart(2, "0") };
}

/** Second line of a payout row: "Paid", "Upcoming · 2 holdings". */
export function payoutStatusText(paid: boolean, count: number): string {
  return `${paid ? "Paid" : "Upcoming"}${count > 1 ? ` · ${count} holdings` : ""}`;
}

/** Paid, Upcoming, or Part paid when the month mixes both. */
export function bucketStatus(items: { paid: boolean }[]): "Paid" | "Upcoming" | "Part paid" {
  const paid = items.filter((i) => i.paid).length;
  if (paid === 0) return "Upcoming";
  return paid === items.length ? "Paid" : "Part paid";
}

export interface HoverRow {
  key: string;
  /** Bond name, plus " · Repayment" for a repayment and " ×N" when N payments were combined. */
  label: string;
  /** Coupons: net of TDS. Repayments: the principal. */
  amount: number;
}

/** Items with the same bond name and kind combined into one row, largest amount first. */
export function groupItems(items: BucketItem[]): HoverRow[] {
  const groups = new Map<string, { name: string; kind: BucketItem["kind"]; count: number; amount: number }>();
  for (const it of items) {
    const key = `${it.kind}|${it.name}`;
    const g = groups.get(key) ?? { name: it.name, kind: it.kind, count: 0, amount: 0 };
    g.count += 1;
    g.amount += it.kind === "redemption" ? it.gross : it.net;
    groups.set(key, g);
  }
  return [...groups.entries()]
    .map(([key, g]) => ({
      key,
      label: `${g.name}${g.kind === "redemption" ? " · Repayment" : ""}${g.count > 1 ? ` ×${g.count}` : ""}`,
      amount: g.amount,
    }))
    .sort((a, b) => b.amount - a.amount || a.label.localeCompare(b.label));
}

export interface HoverSummary {
  title: string;
  status: "Paid" | "Upcoming" | "Part paid";
  /** Headline figure: the month's net coupons, or the repayment when the month has no coupon. */
  amount: number;
  amountLabel: "net" | "repaid";
  /** Gross coupons, or null when the month has no coupon. */
  coupon: number | null;
  tds: number;
  rows: HoverRow[];
  /** Rows left out after the first `maxRows`. */
  more: number;
}

/**
 * Everything the hover card shows for one month. With several bonds it lists the combined rows
 * (top `maxRows` plus a count of the rest); with one bond it lists only the repayment, and only
 * when the month also has coupons (otherwise the headline already is the repayment).
 */
export function hoverSummary(b: MonthBucket, multi: boolean, maxRows = 3): HoverSummary {
  const hasCoupon = b.items.some((i) => i.kind === "coupon");
  const groups = groupItems(b.items);
  let rows = groups;
  if (!multi) rows = hasCoupon ? groups.filter((g) => g.key.startsWith("redemption|")) : [];
  return {
    title: `${b.label} ${b.year}`,
    status: bucketStatus(b.items),
    amount: hasCoupon ? b.net : b.redemption,
    amountLabel: hasCoupon ? "net" : "repaid",
    coupon: hasCoupon ? b.gross : null,
    tds: b.tds,
    rows: rows.slice(0, maxRows),
    more: Math.max(0, rows.length - maxRows),
  };
}

/**
 * Left edge (px) for a card of `cardW` placed beside a bar spanning `barLeft` to `barRight`, in a
 * view `viewW` wide: `gap` to the right of the bar, else `gap` to its left, else (neither side
 * fits) kept inside the view, which is 0 when the card is as wide as the view.
 */
export function cardLeftBeside(
  barLeft: number,
  barRight: number,
  cardW: number,
  viewW: number,
  gap: number,
): number {
  const right = barRight + gap;
  if (right + cardW <= viewW) return right;
  const left = barLeft - gap - cardW;
  if (left >= 0) return left;
  return Math.min(Math.max(0, right), Math.max(0, viewW - cardW));
}

/** "₹1,00,000 back" label above the redemption marker. */
export function redemptionLabel(amount: number): string {
  return `${formatINRWhole(amount)} back`;
}

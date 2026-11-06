import { formatDate, formatINR, formatINRWhole } from "./format";
import type { MfTransaction, Sip, SipStatus } from "./types";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** 1 -> "1st", 2 -> "2nd", 3 -> "3rd", 11 -> "11th", 22 -> "22nd". */
export function ordinal(n: number): string {
  const rest = n % 100;
  if (rest >= 11 && rest <= 13) return `${n}th`;
  switch (n % 10) {
    case 1:
      return `${n}st`;
    case 2:
      return `${n}nd`;
    case 3:
      return `${n}rd`;
    default:
      return `${n}th`;
  }
}

/** Dropdown option label for a day of the month: "5th of Every Month". */
export function dayOptionLabel(day: number): string {
  return `${ordinal(day)} of Every Month`;
}

/** Rupees without ".00" when whole: ₹5,000 or ₹5,000.50. */
export function amountText(n: number): string {
  return Number.isInteger(n) ? formatINRWhole(n) : formatINR(n);
}

/** "₹5,000 on the 5th". */
export function scheduleText(sip: Pick<Sip, "amount" | "day_of_month">): string {
  return `${amountText(sip.amount)} on the ${ordinal(sip.day_of_month)}`;
}

/** "₹5,000 on the 5th of every month". */
export function monthlyScheduleText(sip: Pick<Sip, "amount" | "day_of_month">): string {
  return `${scheduleText(sip)} of every month`;
}

/** "Jan 2026" for an ISO date. */
export function monthYear(iso: string): string {
  const [y, m] = iso.slice(0, 10).split("-").map(Number);
  return `${MONTHS[m - 1]} ${y}`;
}

/** "₹5,000 on the 5th of every month · since Jan 2026". */
export function sinceText(sip: Pick<Sip, "amount" | "day_of_month" | "start_date">): string {
  return `${monthlyScheduleText(sip)} · since ${monthYear(sip.start_date)}`;
}

// ---- Past instalments (start date before today) ----

function parts(iso: string): [number, number, number] {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return [y, m, d];
}

function iso(y: number, m: number, d: number): string {
  return `${String(y).padStart(4, "0")}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

/**
 * Monthly due dates on `day` (1 to 28) from `start` to `today`, both inclusive,
 * oldest first. The first one is the first `day` on or after the start date.
 */
export function pastDueDates(start: string, day: number, today: string): string[] {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(start) || !/^\d{4}-\d{2}-\d{2}$/.test(today)) return [];
  if (!Number.isInteger(day) || day < 1 || day > 28) return [];
  const [startYear, startMonth, startDay] = parts(start);
  let y = startYear;
  let m = startMonth;
  if (startDay > day) {
    m += 1;
    if (m > 12) {
      m = 1;
      y += 1;
    }
  }
  const out: string[] = [];
  for (let due = iso(y, m, day); due <= today; due = iso(y, m, day)) {
    out.push(due);
    m += 1;
    if (m > 12) {
      m = 1;
      y += 1;
    }
  }
  return out;
}

export interface PastInstalments {
  count: number;
  /** "Jan 2026 – Oct 2026", or "Mar 2026" for one; empty when none. */
  range: string;
}

/** How many instalments fall between the start date and today, and which months. */
export function pastInstalments(start: string, day: number, today: string): PastInstalments {
  const dates = pastDueDates(start, day, today);
  if (dates.length === 0) return { count: 0, range: "" };
  const first = monthYear(dates[0]);
  const last = monthYear(dates[dates.length - 1]);
  return { count: dates.length, range: dates.length === 1 ? first : `${first} – ${last}` };
}

/** The Yes/No question shown when the start date is in the past, or null when there is none to ask. */
export function pastQuestion(start: string, day: number, today: string): string | null {
  if (!start || start >= today) return null;
  const past = pastInstalments(start, day, today);
  if (past.count === 0) return null;
  const noun = past.count === 1 ? "instalment" : "instalments";
  return `Add the ${past.count} past ${noun} (${past.range}) to your total?`;
}

/** Helper line under the Yes/No choice. */
export function pastHint(include: boolean): string {
  return include
    ? "Each is added to the holding at its own month's NAV."
    : "Only instalments from today onward are added.";
}

// ---- SIP list ----

export const STATUS_LABELS: Record<SipStatus, string> = {
  active: "Active",
  paused: "Paused",
  stopped: "Cancelled",
};

const STATUS_RANK: Record<SipStatus, number> = { active: 0, paused: 1, stopped: 2 };

/** Columns the SIP grid can sort by. */
export type SipSortKey =
  | "fund_name"
  | "status"
  | "amount"
  | "day_of_month"
  | "next_date"
  | "instalments_added"
  | "invested_via_sip";

export const SIP_SORT_KEYS: readonly SipSortKey[] = [
  "fund_name",
  "status",
  "amount",
  "day_of_month",
  "next_date",
  "instalments_added",
  "invested_via_sip",
];

/** Default order: Active, Paused, Cancelled, then by next instalment date. */
export const DEFAULT_SIP_SORT: SipSortKey = "status";

/** SIPs whose fund or platform contains the search text, limited to the chosen statuses (none chosen = all). */
export function filterSips(sips: Sip[], q: string, statuses: SipStatus[]): Sip[] {
  const needle = q.trim().toLowerCase();
  return sips.filter((s) => {
    if (statuses.length > 0 && !statuses.includes(s.status)) return false;
    if (!needle) return true;
    return (
      s.fund_name.toLowerCase().includes(needle) ||
      platformLabel(s.platform).toLowerCase().includes(needle)
    );
  });
}

function nameCompare(a: Sip, b: Sip): number {
  return a.fund_name.toLowerCase().localeCompare(b.fund_name.toLowerCase());
}

/** Ascending by next date; a missing date goes last. */
function nextCompare(a: Sip, b: Sip): number {
  if (a.next_date === b.next_date) return 0;
  if (a.next_date === null) return 1;
  if (b.next_date === null) return -1;
  return a.next_date < b.next_date ? -1 : 1;
}

/**
 * A sorted copy. Ties fall back to status order, next date, fund name, id, so
 * the default order is Active, Paused, Cancelled, then soonest instalment first.
 * A missing next date stays last in either direction.
 */
export function sortSips(sips: Sip[], key: SipSortKey, desc: boolean): Sip[] {
  const dir = desc ? -1 : 1;
  const primary = (a: Sip, b: Sip): number => {
    switch (key) {
      case "fund_name":
        return dir * nameCompare(a, b);
      case "status":
        return dir * (STATUS_RANK[a.status] - STATUS_RANK[b.status]);
      case "amount":
        return dir * (a.amount - b.amount);
      case "day_of_month":
        return dir * (a.day_of_month - b.day_of_month);
      case "next_date":
        return a.next_date !== null && b.next_date !== null
          ? dir * nextCompare(a, b)
          : nextCompare(a, b);
      case "instalments_added":
        return dir * (a.instalments_added - b.instalments_added);
      case "invested_via_sip":
        return dir * (a.invested_via_sip - b.invested_via_sip);
    }
  };
  return [...sips].sort(
    (a, b) =>
      primary(a, b) ||
      STATUS_RANK[a.status] - STATUS_RANK[b.status] ||
      nextCompare(a, b) ||
      nameCompare(a, b) ||
      a.id - b.id,
  );
}

/** Total of the active SIPs' monthly amounts. */
export function monthlyTotal(sips: Pick<Sip, "amount" | "status">[]): number {
  const total = sips.reduce((sum, s) => (s.status === "active" ? sum + s.amount : sum), 0);
  return Math.round(total * 100) / 100;
}

/** True when the next due instalment is one the user skipped. */
export function isNextSkipped(sip: Pick<Sip, "next_date" | "skipped_dates">): boolean {
  return sip.next_date !== null && sip.skipped_dates.includes(sip.next_date);
}

/** Next-instalment text: "Next 5 Dec 2026", "Skipping 5 Dec 2026", "Paused", "Cancelled". */
export function nextText(
  sip: Pick<Sip, "status" | "next_date" | "skipped_dates">,
): string {
  if (sip.status === "stopped") return "Cancelled";
  if (sip.status === "paused") return "Paused";
  if (!sip.next_date) return "No upcoming instalment";
  return isNextSkipped(sip)
    ? `Skipping ${formatDate(sip.next_date)}`
    : `Next ${formatDate(sip.next_date)}`;
}

/** "12 instalments · ₹60,000 invested", or "No instalments yet". */
export function instalmentsText(
  sip: Pick<Sip, "instalments_added" | "invested_via_sip">,
): string {
  const n = sip.instalments_added;
  if (n === 0) return "No instalments yet";
  return `${n} ${n === 1 ? "instalment" : "instalments"} · ${amountText(sip.invested_via_sip)} invested`;
}

// ---- SIP list: platform, dates, countdown, cycle progress, summary ----

/** "GROWW" or "groww" -> "Groww"; a name already in mixed case ("ET Money") stays as typed. */
export function platformLabel(platform: string): string {
  const text = platform.trim();
  if (text !== text.toUpperCase() && text !== text.toLowerCase()) return text;
  return text
    .split(/\s+/)
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1).toLowerCase() : w))
    .join(" ");
}

/** "2 Dec" for an ISO date. */
export function shortDate(isoDate: string): string {
  const [, m, d] = parts(isoDate);
  return `${d} ${MONTHS[m - 1]}`;
}

function dayNumber(isoDate: string): number {
  const [y, m, d] = parts(isoDate);
  return Math.round(Date.UTC(y, m - 1, d) / 86400000);
}

/** Whole days from `today` to `isoDate` (negative when past). */
export function daysUntil(isoDate: string, today: string): number {
  return dayNumber(isoDate) - dayNumber(today);
}

/** "today", "tomorrow", "in 26 days", or "overdue" for a date already past. */
export function countdownText(isoDate: string, today: string): string {
  const n = daysUntil(isoDate, today);
  if (n < 0) return "overdue";
  if (n === 0) return "today";
  if (n === 1) return "tomorrow";
  return `in ${n} days`;
}

export interface SipSummary {
  activeCount: number;
  /** Monthly total of the active SIPs. */
  monthly: number;
  /** Invested through SIPs, all SIPs. */
  invested: number;
  /** Instalments added, all SIPs. */
  instalments: number;
  /** Earliest upcoming instalment of an active SIP that isn't skipped. */
  nextDate: string | null;
}

export function sipSummary(
  sips: Pick<Sip, "status" | "amount" | "next_date" | "skipped_dates" | "invested_via_sip" | "instalments_added">[],
): SipSummary {
  let nextDate: string | null = null;
  for (const s of sips) {
    if (s.status !== "active" || !s.next_date || isNextSkipped(s)) continue;
    if (nextDate === null || s.next_date < nextDate) nextDate = s.next_date;
  }
  return {
    activeCount: sips.filter((s) => s.status === "active").length,
    monthly: monthlyTotal(sips),
    invested: Math.round(sips.reduce((sum, s) => sum + s.invested_via_sip, 0) * 100) / 100,
    instalments: sips.reduce((sum, s) => sum + s.instalments_added, 0),
    nextDate,
  };
}

/** "2 active · next 2 Dec 2026", or "No active SIPs". */
export function summaryLine(summary: SipSummary): string {
  if (summary.activeCount === 0) return "No active SIPs";
  const head = `${summary.activeCount} active`;
  if (!summary.nextDate) return head;
  return `${head} · next ${formatDate(summary.nextDate)}`;
}

export type SipActionKey = "edit" | "skip" | "undo" | "pause" | "resume" | "stop" | "delete";

/** Menu labels (Title Case). */
export const ACTION_LABELS: Record<SipActionKey, string> = {
  edit: "Update SIP",
  skip: "Skip Next",
  undo: "Undo Skip",
  pause: "Pause SIP",
  resume: "Resume SIP",
  stop: "Cancel SIP",
  delete: "Delete SIP",
};

/** Actions offered for a SIP, in menu order. Skip turns into Undo while the next instalment is skipped. */
export function availableActions(
  sip: Pick<Sip, "status" | "next_date" | "skipped_dates">,
): SipActionKey[] {
  if (sip.status === "stopped") return ["delete"];
  if (sip.status === "paused") return ["edit", "resume", "stop"];
  const out: SipActionKey[] = ["edit"];
  if (sip.next_date) out.push(isNextSkipped(sip) ? "undo" : "skip");
  out.push("pause", "stop");
  return out;
}

/** API path of a SIP action that needs no body. */
export function actionPath(
  sip: Pick<Sip, "id" | "next_date">,
  action: "pause" | "resume" | "stop" | "skip" | "undo",
): string {
  switch (action) {
    case "undo":
      return `/sips/${sip.id}/skip/${sip.next_date ?? ""}`;
    default:
      return `/sips/${sip.id}/${action}`;
  }
}

// ---- MF transactions ----

/** "SIP" for an instalment added by a SIP, else "Purchase" or "Redemption". */
export function transactionLabel(t: Pick<MfTransaction, "kind" | "sip">): string {
  if (t.sip) return "SIP";
  return t.kind === "redemption" ? "Redemption" : "Purchase";
}

/** Button text under a paged list: "Show 10 more · 26 left", "Show 6 more", or null when all are shown. */
export function showMoreLabel(total: number, loaded: number, pageSize = 10): string | null {
  const left = total - loaded;
  if (left <= 0) return null;
  return left <= pageSize ? `Show ${left} more` : `Show ${pageSize} more · ${left} left`;
}

export const SIPS_VIEW_HREF = "/portfolio/mf?view=sips";
export const ADD_SIP_HREF = "/add/mf?tab=sip";

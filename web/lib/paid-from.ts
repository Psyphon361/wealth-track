import type { ReinvestPrefill } from "./reinvest";
import type { AssetType, PaidFrom } from "./types";

// Messages shared verbatim with the API (re-exported by components/forms/schema.ts).
export const PAID_FROM_BALANCE_ERROR = "More than this account's balance";
export const PAID_FROM_AMOUNT_ERROR =
  "Enter the amount invested to pay it from an account";
export const PAID_FROM_ACCOUNT_ERROR = "Choose one of your accounts";
// Editing the cost of a holding paid from an account (the API fills in {account} and {shortfall}).
export const PAID_FROM_EDIT_TOO_MUCH_ERROR =
  "Not enough in {account}: short by {shortfall}";
export const PAID_FROM_EDIT_DELETED_ERROR = "Restore {account} first";
export const PAID_FROM_EDIT_ZERO_ERROR =
  "The cost must stay above zero while it is paid from an account";
export const PAID_FROM_EDIT_NOT_IN_SYNC_NOTE =
  "The cost no longer matches the amount paid from {account}, so the account was not changed.";
export const PAID_FROM_EDIT_GONE_NOTE =
  "The account it was paid from no longer exists, so no money moved.";

function parseISO(iso: string): [number, number, number] | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return null;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const dt = new Date(Date.UTC(y, mo - 1, d));
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== mo - 1 || dt.getUTCDate() !== d) {
    return null;
  }
  return [y, mo, d];
}

function fmtISO(dt: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${String(dt.getUTCFullYear()).padStart(4, "0")}-${p(dt.getUTCMonth() + 1)}-${p(dt.getUTCDate())}`;
}

/** Add months, clamping to the end of the target month (like relativedelta). */
function addMonths(iso: string, months: number): string {
  const p = parseISO(iso);
  if (!p) return iso;
  const total = p[0] * 12 + (p[1] - 1) + months;
  const y = Math.floor(total / 12);
  const m = total - y * 12;
  const dim = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
  return fmtISO(new Date(Date.UTC(y, m, Math.min(p[2], dim))));
}

function addDays(iso: string, days: number): string {
  const p = parseISO(iso);
  if (!p) return iso;
  return fmtISO(new Date(Date.UTC(p[0], p[1] - 1, p[2] + days)));
}

function todayISO(): string {
  const n = new Date();
  const p = (x: number) => String(x).padStart(2, "0");
  return `${n.getFullYear()}-${p(n.getMonth() + 1)}-${p(n.getDate())}`;
}

export const PAID_FROM_LABEL = "Paid From";
export const OUTSIDE_MONEY_LABEL = "Outside Money (New Money)";
export const PAID_FROM_HELPER =
  "Bought with money already in one of your accounts? Pick it so it isn't counted twice.";

/** An active Cash & Savings account the user can pay from. */
export interface PaidFromAccount {
  id: number;
  name: string;
  balance: number;
}

/** What the API returns on a holding (`paid_from`). */
export type PaidFromRecord = PaidFrom;

/** The `paid_from` body sent on create. */
export interface PaidFromBody {
  cash_id: number;
  from_exit_id?: number;
}

type Values = Record<string, unknown>;

function num(v: unknown): number | null {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v !== "string" || v.trim() === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/** Instalments of an RD paid on or before `today`, counted as the API does (before maturity). */
export function rdInstalmentsPaid(
  start: string,
  years: number,
  months: number,
  days: number,
  today: string = todayISO(),
): number {
  if (!parseISO(start)) return 0;
  const maturity = addDays(addMonths(start, years * 12 + months), days);
  let count = 0;
  // Bounded: the form allows at most 10 years of tenure.
  for (let k = 0; k < 1200; k++) {
    const d = addMonths(start, k);
    if (d >= maturity || d > today) break;
    count++;
  }
  return count;
}

/**
 * The amount taken off the account for a holding with these form values, or
 * null while it can't be worked out (a blank or invalid amount).
 */
export function paidFromAmount(
  type: AssetType,
  v: Values,
  today: string = todayISO(),
): number | null {
  let n: number | null;
  switch (type) {
    case "fd":
      n = num(v.principal);
      break;
    case "rd": {
      const inst = num(v.monthly_instalment);
      const start = typeof v.start_date === "string" ? v.start_date : "";
      if (inst === null) return null;
      const count = rdInstalmentsPaid(
        start,
        num(v.tenure_years) ?? 0,
        num(v.tenure_months) ?? 0,
        num(v.tenure_days) ?? 0,
        today,
      );
      n = Math.round(count * inst * 100) / 100;
      break;
    }
    case "stock": {
      const q = num(v.quantity);
      const p = num(v.avg_buy_price);
      n = q !== null && p !== null ? Math.round(q * p * 100) / 100 : null;
      break;
    }
    case "bond":
    case "mf":
    case "gold":
    case "other":
      n = num(v.invested_amount);
      break;
    case "nps":
      n = num(v.contributed);
      break;
    case "cash":
      n = num(v.balance);
      break;
    case "pf":
      n = num(v.contributed) ?? num(v.balance);
      break;
  }
  return n !== null && n > 0 ? n : null;
}

/** Whole rupees when there are no paise, else two decimals; Indian grouping. */
export function inr(n: number): string {
  const whole = Math.abs(n - Math.round(n)) < 0.005;
  return `₹${new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: whole ? 0 : 2,
    maximumFractionDigits: whole ? 0 : 2,
  }).format(whole ? Math.round(n) : n)}`;
}

export function accountLabel(a: Pick<PaidFromAccount, "name" | "balance">): string {
  return `${a.name} · ${inr(a.balance)}`;
}

/** "HDFC Savings: ₹2,25,000 → ₹1,75,000". */
export function paidFromEffect(a: PaidFromAccount, amount: number): string {
  const after = Math.round((a.balance - amount) * 100) / 100;
  return `${a.name}: ${inr(a.balance)} → ${inr(after)}`;
}

/**
 * The validation message for the chosen account, or null when fine. Same
 * wording as the API. `account` is null when none is chosen (always valid)
 * unless `cashId` is set but isn't one of the user's accounts.
 */
export function paidFromError(
  type: AssetType,
  cashId: number | null,
  accounts: PaidFromAccount[] | null,
  amount: number | null,
): string | null {
  if (cashId === null) return null;
  if (accounts === null) return null;
  const account = accounts.find((a) => a.id === cashId);
  if (!account) return PAID_FROM_ACCOUNT_ERROR;
  if (amount === null) return type === "other" ? PAID_FROM_AMOUNT_ERROR : null;
  if (amount > account.balance) return PAID_FROM_BALANCE_ERROR;
  return null;
}

export function paidFromBody(
  cashId: number | null,
  fromExitId?: number,
): { paid_from: PaidFromBody } | Record<string, never> {
  if (cashId === null) return {};
  return {
    paid_from:
      fromExitId === undefined
        ? { cash_id: cashId }
        : { cash_id: cashId, from_exit_id: fromExitId },
  };
}

/** Read-only line for the Edit dialog: "Paid from HDFC Savings · ₹50,000". */
export function paidFromReadOnly(p: PaidFromRecord): string {
  const name = p.cash_name ?? "a deleted account";
  return `Paid from ${name} · ${inr(p.amount)}`;
}

/** The record's `paid_from`, if the API sent one. */
export function recordPaidFrom(
  record: { paid_from?: PaidFromRecord | null } | null | undefined,
): PaidFromRecord | null {
  return record?.paid_from ?? null;
}

export function reinvestNote(p: ReinvestPrefill): string {
  return `Reinvesting ${inr(p.amount)} from ${p.cash_name}.`;
}

/** Form field that takes the reinvested amount, per type (none: shown as a hint). */
export const REINVEST_AMOUNT_FIELD: Partial<Record<AssetType, string>> = {
  fd: "principal",
  bond: "invested_amount",
  mf: "invested_amount",
  gold: "invested_amount",
  other: "invested_amount",
  nps: "contributed",
  cash: "balance",
  pf: "contributed",
};

/** Form field that takes the reinvestment date, per type. */
export const REINVEST_DATE_FIELD: Record<AssetType, string> = {
  fd: "start_date",
  rd: "start_date",
  stock: "buy_date",
  bond: "purchase_date",
  mf: "purchase_date",
  gold: "purchase_date",
  nps: "start_date",
  cash: "balance_date",
  pf: "balance_date",
  other: "acquired_on",
};

/** Hint for types with no single amount field: "₹50,000 to invest". */
export function reinvestHint(p: ReinvestPrefill): string {
  return `${inr(p.amount)} to invest`;
}

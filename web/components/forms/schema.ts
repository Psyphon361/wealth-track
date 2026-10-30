import { z } from "zod";

// ---- Limits and messages (shared with API validation rules) ----

export const MAX_MONEY = 1_000_000_000;
export const MAX_MONEY_ERROR = "Must be at most ₹100 crore";
export const MAX_QUANTITY = 10_000_000;
export const MAX_QUANTITY_ERROR = "Must be at most 1 crore";
export const MAX_TEXT = 200;
export const MAX_NOTES = 1000;
export const MAX_ISIN = 12;
export const MAX_SYMBOL = 20;
export const MIN_DATE = "1990-01-01";
export const MIN_DATE_ERROR = "Date must be on or after 1 Jan 1990";
export const FUTURE_DAYS = 30;
export const FUTURE_DATE_ERROR = "Date can be at most 30 days in the future";
export const FD_TENURE_ERROR = "FD tenure must be between 7 days and 10 years";
export const RD_TENURE_ERROR =
  "RD tenure must be between 6 months and 10 years";
export const TENURE_ERROR = "Tenure must be greater than zero";
export const MATURITY_RANGE_ERROR = "Maturity must be within 50 years of purchase";
export const BOND_AMOUNT_MISMATCH_ERROR =
  "Total invested must equal quantity × purchase price";
export const MF_AMOUNT_MISMATCH_ERROR =
  "Total invested must equal units × average NAV";
export const FD_RATE_ERROR = "Interest rate must be between 0 and 15%";
export const YTM_ERROR = "YTM must be between 0 and 30%";
export const ISIN_ERROR = "ISIN must be 12 characters, e.g. INE002A01018";
export const SYMBOL_ERROR =
  "Symbol: letters, digits, & or -, up to 20 characters";
export const PAYOUT_FREQUENCY_ERROR = "Choose a payout frequency";
export const SCHEME_REQUIRED_ERROR = "Select a scheme from the list";
export const STOCK_REQUIRED_ERROR = "Select a stock from the list";
export const BOND_REQUIRED_ERROR = "Select a bond from the list";
export const ISSUER_REQUIRED_ERROR = "Select a bank or issuer from the list";
export const EMAIL_ERROR = "Enter a valid email address";
export const PASSWORD_MIN = 10;
export const PASSWORD_MAX = 128;
export const PASSWORD_MIN_ERROR = "Password must be at least 10 characters";
export const PASSWORD_MAX_ERROR = "Password must be at most 128 characters";
export const PASSWORD_REQUIRED_ERROR = "Required";
export const MAX_TENURE_YEARS = 10;
export const MAX_BOND_YEARS = 50;

// ---- Date arithmetic (ISO "YYYY-MM-DD" strings, timezone independent) ----

const ISO_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

function fmtISO(y: number, m: number, d: number): string {
  return `${String(y).padStart(4, "0")}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

function parseISO(iso: string): [number, number, number] | null {
  const m = ISO_RE.exec(iso);
  if (!m) return null;
  const y = Number(m[1]);
  const mo = Number(m[2]);
  const d = Number(m[3]);
  const dt = new Date(Date.UTC(y, mo - 1, d));
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== mo - 1) return null;
  if (dt.getUTCDate() !== d) return null;
  return [y, mo, d];
}

export function isValidISODate(iso: string): boolean {
  return parseISO(iso) !== null;
}

export function addDaysISO(iso: string, days: number): string {
  const p = parseISO(iso);
  if (!p) return iso;
  const dt = new Date(Date.UTC(p[0], p[1] - 1, p[2] + days));
  return fmtISO(dt.getUTCFullYear(), dt.getUTCMonth() + 1, dt.getUTCDate());
}

/** Add months, clamping to the end of the target month (like relativedelta). */
export function addMonthsISO(iso: string, months: number): string {
  const p = parseISO(iso);
  if (!p) return iso;
  const total = p[0] * 12 + (p[1] - 1) + months;
  const y = Math.floor(total / 12);
  const m = total - y * 12;
  const dim = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
  return fmtISO(y, m + 1, Math.min(p[2], dim));
}

/** Years, then months (clamped to month end), then days. */
export function addPeriodISO(
  iso: string,
  years: number,
  months: number,
  days: number,
): string {
  return addDaysISO(addMonthsISO(iso, years * 12 + months), days);
}

/**
 * Inverse of addPeriodISO: largest whole months k with addMonthsISO(start, k) <= end,
 * then the remaining days. Zeros if end <= start or a date is invalid.
 */
export function diffPeriodISO(
  start: string,
  end: string,
): { years: number; months: number; days: number } {
  const zero = { years: 0, months: 0, days: 0 };
  const s = parseISO(start);
  const e = parseISO(end);
  if (!s || !e || end <= start) return zero;
  let k = (e[0] - s[0]) * 12 + (e[1] - s[1]);
  while (k > 0 && addMonthsISO(start, k) > end) k--;
  const rest = addMonthsISO(start, k);
  const days = Math.round(
    (Date.UTC(e[0], e[1] - 1, e[2]) -
      Date.UTC(
        Number(rest.slice(0, 4)),
        Number(rest.slice(5, 7)) - 1,
        Number(rest.slice(8, 10)),
      )) /
      86400000,
  );
  return { years: Math.floor(k / 12), months: k % 12, days };
}

export function todayISO(): string {
  const n = new Date();
  return fmtISO(n.getFullYear(), n.getMonth() + 1, n.getDate());
}

export function maxFutureDateISO(): string {
  return addDaysISO(todayISO(), FUTURE_DAYS);
}

export type TenureKind = "fd" | "rd";

export function tenureInRange(
  kind: TenureKind,
  start: string,
  years: number,
  months: number,
  days: number,
): boolean {
  if (!isValidISODate(start)) return true;
  const maturity = addPeriodISO(start, years, months, days);
  const min =
    kind === "fd" ? addDaysISO(start, 7) : addMonthsISO(start, 6);
  const max = addMonthsISO(start, MAX_TENURE_YEARS * 12);
  return maturity >= min && maturity <= max;
}

export function maturityWithinLimit(
  purchase: string,
  maturity: string,
): boolean {
  if (!isValidISODate(purchase) || !isValidISODate(maturity)) return true;
  return maturity <= addMonthsISO(purchase, MAX_BOND_YEARS * 12);
}

// ---- Zod pieces ----

const tooLong = (n: number) => `Must be at most ${n} characters`;

export const requiredText = z
  .string()
  .trim()
  .min(1, "Required")
  .max(MAX_TEXT, tooLong(MAX_TEXT));

function optionalTextMax(max: number) {
  return z
    .string()
    .trim()
    .max(max, tooLong(max))
    .transform((v): string | null => (v === "" ? null : v));
}

export const optionalText = optionalTextMax(MAX_TEXT);
export const notesText = optionalTextMax(MAX_NOTES);

export const isinText = z
  .string()
  .trim()
  .transform((v) => v.toUpperCase())
  .refine((v) => v === "" || /^[A-Z]{2}[A-Z0-9]{9}[0-9]$/.test(v), ISIN_ERROR)
  .transform((v): string | null => (v === "" ? null : v));

export const symbolText = z
  .string()
  .trim()
  .transform((v) => v.toUpperCase())
  .refine((v) => v === "" || /^[A-Z0-9&-]{1,20}$/.test(v), SYMBOL_ERROR)
  .transform((v): string | null => (v === "" ? null : v));

const dateBase = z
  .string()
  .min(1, "Required")
  .refine((v) => !isValidISODate(v) || v >= MIN_DATE, MIN_DATE_ERROR);

/** Any date: required, on or after 1 Jan 1990. */
export const dateString = dateBase;

/** Start / buy / purchase date: also at most 30 days in the future. */
export const startDateString = dateBase.refine(
  (v) => !isValidISODate(v) || v <= maxFutureDateISO(),
  FUTURE_DATE_ERROR,
);

const numberString = z
  .string()
  .trim()
  .min(1, "Required")
  .refine((v) => Number.isFinite(Number(v)), "Enter a valid number")
  .transform(Number);

export const positiveNumber = numberString.refine(
  (n) => n > 0,
  "Must be greater than 0",
);

/** Rupee amount: > 0 and at most ₹100 crore. */
export const moneyNumber = positiveNumber.refine(
  (n) => n <= MAX_MONEY,
  MAX_MONEY_ERROR,
);

/** Percentage rate: > 0, at most `max`, at most 2 decimals. */
export function rateNumber(max: number, message: string) {
  return numberString
    .refine((n) => n > 0 && n <= max, message)
    .refine(
      (n) => Math.abs(n * 100 - Math.round(n * 100)) < 1e-6,
      "Up to 2 decimal places allowed",
    );
}

export const positiveInteger = positiveNumber
  .refine(Number.isInteger, "Must be a whole number")
  .refine((n) => n <= MAX_QUANTITY, MAX_QUANTITY_ERROR);

export const positiveUnits = positiveNumber
  .refine(
    (n) => Math.abs(n * 1000 - Math.round(n * 1000)) < 1e-6,
    "Up to 3 decimal places allowed",
  )
  .refine((n) => n <= MAX_QUANTITY, MAX_QUANTITY_ERROR);

export const tenurePart = z.string().transform(Number);

export function tenureIsPositive(v: {
  tenure_years: number;
  tenure_months: number;
  tenure_days: number;
}): boolean {
  return v.tenure_years + v.tenure_months + v.tenure_days > 0;
}

export function tenureOk(
  kind: TenureKind,
  v: {
    start_date: string;
    tenure_years: number;
    tenure_months: number;
    tenure_days: number;
  },
): boolean {
  if (!tenureIsPositive(v)) return true;
  return tenureInRange(
    kind,
    v.start_date,
    v.tenure_years,
    v.tenure_months,
    v.tenure_days,
  );
}

export const compoundingEnum = z.enum([
  "monthly",
  "quarterly",
  "half_yearly",
  "yearly",
  "simple",
]);
export const payoutEnum = z.enum(["cumulative", "payout"]);
export const exchangeEnum = z.enum(["NSE", "BSE"]);
export const bondTypeEnum = z.enum([
  "government",
  "corporate",
  "tax_free",
  "sgb",
  "other",
]);
export const mfCategoryEnum = z.enum([
  "equity",
  "debt",
  "hybrid",
  "index",
  "elss",
  "liquid",
  "other",
]);

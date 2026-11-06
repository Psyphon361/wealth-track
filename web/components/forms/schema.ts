import { z } from "zod";
import {
  GOLD_PURITIES_BY_METAL,
  type GoldMetal,
  type GoldPurity,
} from "@/lib/types";

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
export const GOLD_METAL_ERROR = "Choose a metal";
export const GOLD_FORM_ERROR = "Choose a form";
export const GOLD_PURITY_ERROR = "Choose a purity";
export const GOLD_WEIGHT_DECIMALS_ERROR =
  "Weight can have at most 3 decimal places";
export const CASH_KIND_ERROR = "Choose an account type";
export const PF_KIND_ERROR = CASH_KIND_ERROR;
export const PF_OPENED_ON_ERROR = "Enter the opening date";
export const NPS_SCHEME_ERROR = "Choose a scheme";
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

export const OTHER_ACQUIRED_AFTER_VALUE_ERROR =
  "Purchase date can't be after the value date";
export const MAX_CATEGORY = 40;

export const categoryText = z
  .string()
  .trim()
  .min(1, "Required")
  .max(MAX_CATEGORY, tooLong(MAX_CATEGORY));

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

/** Optional percentage rate: blank becomes null, else same checks as rateNumber. */
export function optionalRate(max: number, message: string) {
  const rate = rateNumber(max, message);
  return z
    .string()
    .trim()
    .transform((v, ctx): number | null => {
      if (v === "") return null;
      const r = rate.safeParse(v);
      if (!r.success) {
        for (const i of r.error.issues) ctx.addIssue({ code: "custom", message: i.message });
        return z.NEVER;
      }
      return r.data;
    });
}

/** Optional rupee amount: blank becomes null, else same checks as moneyNumber. */
export const optionalMoney = z
  .string()
  .trim()
  .transform((v, ctx): number | null => {
    if (v === "") return null;
    const r = moneyNumber.safeParse(v);
    if (!r.success) {
      for (const i of r.error.issues) ctx.addIssue({ code: "custom", message: i.message });
      return z.NEVER;
    }
    return r.data;
  });

export const positiveInteger = positiveNumber
  .refine(Number.isInteger, "Must be a whole number")
  .refine((n) => n <= MAX_QUANTITY, MAX_QUANTITY_ERROR);

export const positiveUnits = positiveNumber
  .refine(
    (n) => Math.abs(n * 1000 - Math.round(n * 1000)) < 1e-6,
    "Up to 3 decimal places allowed",
  )
  .refine((n) => n <= MAX_QUANTITY, MAX_QUANTITY_ERROR);

/** NPS units: > 0, at most 4 decimals, at most 1 crore. */
export const npsUnits = positiveNumber
  .refine(
    (n) => Math.abs(n * 10000 - Math.round(n * 10000)) < 1e-6,
    "Up to 4 decimal places allowed",
  )
  .refine((n) => n <= MAX_QUANTITY, MAX_QUANTITY_ERROR);

/** Gold weight in grams: > 0, at most 3 decimals, at most 1 crore. */
export const goldWeight = positiveNumber
  .refine(
    (n) => Math.abs(n * 1000 - Math.round(n * 1000)) < 1e-6,
    GOLD_WEIGHT_DECIMALS_ERROR,
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
export const goldFormEnum = z.enum(["jewellery", "coin", "bar", "digital"], {
  error: GOLD_FORM_ERROR,
});
export const goldMetalEnum = z.enum(["gold", "silver"], {
  error: GOLD_METAL_ERROR,
});
export const goldPurityEnum = z.enum(["999", "995", "916", "750", "585", "925"], {
  error: GOLD_PURITY_ERROR,
});
/** Purity must belong to the metal (same rule as the API). */
export function isPurityForMetal(metal: string, purity: string): boolean {
  const allowed = GOLD_PURITIES_BY_METAL[metal as GoldMetal];
  return !!allowed && allowed.includes(purity as GoldPurity);
}
export const cashKindEnum = z.enum(["savings", "current", "cash", "other"], {
  error: CASH_KIND_ERROR,
});
export const pfKindEnum = z.enum(["epf", "vpf", "ppf"], {
  error: PF_KIND_ERROR,
});
export const mfCategoryEnum =z.enum([
  "equity",
  "debt",
  "hybrid",
  "index",
  "elss",
  "liquid",
  "other",
]);

// ---- SIP rules (same wording as api/app/schemas/sip.py) ----

export const SIP_MIN_AMOUNT = 100;
export const SIP_AMOUNT_MIN_ERROR = "Must be at least ₹100";
export const SIP_DAY_ERROR = "Day must be between 1 and 28";
export const SIP_START_FUTURE_ERROR = "Date can be at most 1 year in the future";
export const SIP_END_BEFORE_START_ERROR =
  "End date must be on or after the start date";
export const SIP_FUTURE_DAYS = 366;

/** Latest allowed SIP start date: one year from today. */
export function maxSipStartDateISO(): string {
  return addDaysISO(todayISO(), SIP_FUTURE_DAYS);
}

/** Monthly SIP amount: at least ₹100, at most ₹100 crore, 2 decimals. */
export const sipAmount = z
  .string()
  .trim()
  .min(1, "Required")
  .refine((v) => Number.isFinite(Number(v)), "Enter a valid number")
  .transform(Number)
  .refine((n) => n >= SIP_MIN_AMOUNT, SIP_AMOUNT_MIN_ERROR)
  .refine(
    (n) => Math.abs(n * 100 - Math.round(n * 100)) < 1e-6,
    "Up to 2 decimal places allowed",
  )
  .refine((n) => n <= MAX_MONEY, MAX_MONEY_ERROR);

/** Day of the month (1 to 28, so it exists in every month). */
export const sipDay = z
  .string()
  .min(1, "Required")
  .transform(Number)
  .refine((n) => Number.isInteger(n) && n >= 1 && n <= 28, SIP_DAY_ERROR);

/** SIP start date: on or after 1 Jan 1990, at most a year ahead. */
export const sipStartDate = dateBase.refine(
  (v) => !isValidISODate(v) || v <= maxSipStartDateISO(),
  SIP_START_FUTURE_ERROR,
);

/** Optional SIP end date: blank becomes null, else on or after 1 Jan 1990. */
export const optionalSipEndDate = z
  .string()
  .trim()
  .refine((v) => v === "" || !isValidISODate(v) || v >= MIN_DATE, MIN_DATE_ERROR)
  .transform((v): string | null => (v === "" ? null : v));

/** True when the end date (if any) is on or after the start date. */
export function sipEndAfterStart(
  start: string,
  end: string | null,
): boolean {
  if (!end || !isValidISODate(start) || !isValidISODate(end)) return true;
  return end >= start;
}

import { z } from "zod";

export const requiredText = z.string().trim().min(1, "Required");

export const optionalText = z
  .string()
  .trim()
  .transform((v): string | null => (v === "" ? null : v));

export const dateString = z.string().min(1, "Required");

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

export const positiveInteger = positiveNumber.refine(
  Number.isInteger,
  "Must be a whole number",
);

export const positiveUnits = positiveNumber.refine(
  (n) => Math.abs(n * 1000 - Math.round(n * 1000)) < 1e-6,
  "Up to 3 decimal places allowed",
);

export const tenurePart = z.string().transform(Number);

export function tenureIsPositive(v: {
  tenure_years: number;
  tenure_months: number;
  tenure_days: number;
}): boolean {
  return v.tenure_years + v.tenure_months + v.tenure_days > 0;
}

export const TENURE_ERROR = "Tenure must be greater than zero";

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

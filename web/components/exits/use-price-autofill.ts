"use client";

import { useEffect, useState } from "react";
import type { UseFormSetValue } from "react-hook-form";
import { apiGet } from "@/lib/api";
import {
  priceFieldText,
  priceHint,
  priceRequestPath,
  readPrice,
  type PriceOnDate,
  type PriceSource,
} from "@/lib/exits";

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const DEBOUNCE_MS = 200;
const NO_PRICE = "No price for this date — enter it";

type Result =
  | { key: string; kind: "ok"; found: PriceOnDate }
  | { key: string; kind: "error" };

/**
 * Fills the sale price with the stock close, MF NAV or gold rate on the sale date, unless the
 * user typed their own. Returns the helper text for under the field (or null).
 */
export function usePriceAutofill({
  source,
  date,
  price,
  setValue,
}: {
  source: PriceSource | null;
  date: string;
  price: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  setValue: UseFormSetValue<any>;
}): string | null {
  const [result, setResult] = useState<Result | null>(null);
  // Value we filled in ourselves.
  const [autoText, setAutoText] = useState<string | null>(null);

  const manual = price !== "" && price !== autoText;
  const path = source && ISO_DATE.test(date) ? priceRequestPath(source, date) : null;
  const kind = source?.kind ?? null;
  const wantKey = path !== null && kind !== null && !manual ? path : null;

  useEffect(() => {
    if (wantKey === null || kind === null) return;
    let cancelled = false;
    // No price for this date: drop the one we filled for the previous date.
    const clearAuto = () => {
      setAutoText(null);
      setResult({ key: wantKey, kind: "error" });
      setValue("price", "", { shouldDirty: true });
    };
    const timer = setTimeout(() => {
      apiGet<unknown>(wantKey)
        .then((raw) => {
          if (cancelled) return;
          const found = readPrice(kind, raw);
          if (!found) {
            clearAuto();
            return;
          }
          const text = priceFieldText(found.price);
          setAutoText(text);
          setResult({ key: wantKey, kind: "ok", found });
          setValue("price", text, { shouldDirty: true, shouldValidate: true });
        })
        .catch(() => {
          if (cancelled) return;
          clearAuto();
        });
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [wantKey, kind, setValue]);

  if (wantKey === null) return null;
  if (!result || result.key !== wantKey) return "Fetching price…";
  if (result.kind === "error") return NO_PRICE;
  if (price !== autoText) return null;
  return priceHint(result.found);
}

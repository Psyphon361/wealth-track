"use client";

import { useEffect, useState } from "react";
import type { UseFormSetValue } from "react-hook-form";
import { apiGet, toApiMessage } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { MfNavResponse } from "@/lib/types";

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const DEBOUNCE_MS = 200;

type NavResult =
  | { key: string; kind: "ok"; nav: MfNavResponse }
  | { key: string; kind: "error"; message: string };

/**
 * Fills the Average NAV from the AMFI NAV on the purchase date.
 * Returns the hint text to show under the field (or null).
 */
export function useNavAutofill({
  enabled,
  schemeCode,
  purchaseDate,
  avgNav,
  setValue,
  onFilled,
}: {
  enabled: boolean;
  schemeCode: number | null;
  purchaseDate: string;
  avgNav: string;
  /** Called just before Avg NAV is filled (must be referentially stable). */
  onFilled?: () => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  setValue: UseFormSetValue<any>;
}): string | null {
  const [result, setResult] = useState<NavResult | null>(null);
  // Value we filled in ourselves.
  const [autoText, setAutoText] = useState<string | null>(null);
  // Saved record (edit mode) as the dialog opened.
  const [initial] = useState({ avgNav, schemeCode, purchaseDate });

  // The user's own value: anything non-empty that we didn't fill and isn't the saved one.
  const manual =
    avgNav !== "" && avgNav !== autoText && avgNav !== initial.avgNav;
  const untouchedSaved =
    initial.avgNav !== "" &&
    schemeCode === initial.schemeCode &&
    purchaseDate === initial.purchaseDate;
  const wantKey =
    enabled &&
    schemeCode !== null &&
    ISO_DATE.test(purchaseDate) &&
    !manual &&
    !untouchedSaved
      ? `${schemeCode}|${purchaseDate}`
      : null;

  useEffect(() => {
    if (wantKey === null) return;
    const [code, date] = wantKey.split("|");
    let cancelled = false;
    const timer = setTimeout(() => {
      apiGet<MfNavResponse>(`/master/mf/${code}/nav?date=${date}`)
        .then((nav) => {
          if (cancelled) return;
          const text = nav.nav.toFixed(4);
          setAutoText(text);
          setResult({ key: wantKey, kind: "ok", nav });
          onFilled?.();
          setValue("avg_nav", text, { shouldDirty: true, shouldValidate: true });
        })
        .catch((err) => {
          if (cancelled) return;
          setResult({
            key: wantKey,
            kind: "error",
            message: toApiMessage(err).message,
          });
        });
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [wantKey, setValue, onFilled]);

  if (wantKey === null) return null;
  if (!result || result.key !== wantKey) return "Fetching NAV…";
  if (result.kind === "error") return result.message;
  if (avgNav !== autoText) return null;
  const { nav } = result;
  const base = `NAV on ${formatDate(nav.nav_date)} · AMFI`;
  return nav.nav_date !== nav.requested_date
    ? `${base} (last NAV before ${formatDate(nav.requested_date)})`
    : base;
}

"use client";

import { useEffect, useState } from "react";
import type { UseFormSetValue } from "react-hook-form";
import { apiGet, toApiMessage } from "@/lib/api";
import { formatDate, formatINR } from "@/lib/format";
import type { GoldRateResponse } from "@/lib/types";

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const DEBOUNCE_MS = 200;

type RateResult =
  | { key: string; kind: "ok"; rate: GoldRateResponse }
  | { key: string; kind: "error"; message: string };

/**
 * Fills Total invested = weight x IBJA rate per gram for the metal and purity on the
 * purchase date. Returns the hint text to show under the field (or null).
 */
export function useGoldRateAutofill({
  enabled,
  metal,
  purity,
  purchaseDate,
  weight,
  invested,
  setValue,
}: {
  enabled: boolean;
  metal: string;
  purity: string;
  purchaseDate: string;
  weight: string;
  invested: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  setValue: UseFormSetValue<any>;
}): string | null {
  const [result, setResult] = useState<RateResult | null>(null);
  // Value we filled in ourselves.
  const [autoText, setAutoText] = useState<string | null>(null);
  // Saved record (edit mode) as the dialog opened.
  const [initial] = useState({ invested, metal, purity, purchaseDate });

  // The user's own value: anything non-empty that we didn't fill and isn't the saved one.
  const manual =
    invested !== "" && invested !== autoText && invested !== initial.invested;
  const untouchedSaved =
    initial.invested !== "" &&
    metal === initial.metal &&
    purity === initial.purity &&
    purchaseDate === initial.purchaseDate;
  const wantKey =
    enabled &&
    purity !== "" &&
    ISO_DATE.test(purchaseDate) &&
    !manual &&
    !untouchedSaved
      ? `${metal}|${purity}|${purchaseDate}`
      : null;

  useEffect(() => {
    if (wantKey === null) return;
    const [m, p, date] = wantKey.split("|");
    let cancelled = false;
    const timer = setTimeout(() => {
      apiGet<GoldRateResponse>(`/master/gold/rate?metal=${m}&purity=${p}&date=${date}`)
        .then((rate) => {
          if (cancelled) return;
          setResult({ key: wantKey, kind: "ok", rate });
        })
        .catch((err) => {
          if (cancelled) return;
          const m = toApiMessage(err);
          setResult({
            key: wantKey,
            kind: "error",
            message: [m.message, m.description].filter(Boolean).join(". "),
          });
        });
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [wantKey]);

  const weightNum = Number(weight);
  const readyRate =
    wantKey !== null && result?.key === wantKey && result.kind === "ok"
      ? result.rate
      : null;
  const fillText =
    readyRate && weight !== "" && Number.isFinite(weightNum) && weightNum > 0
      ? (Math.round(weightNum * readyRate.rate_per_gram * 100) / 100).toFixed(2)
      : null;

  useEffect(() => {
    if (fillText === null || fillText === invested) return;
    // Syncs the filled value with the form field, an external store.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setAutoText(fillText);
    setValue("invested_amount", fillText, {
      shouldDirty: true,
      shouldValidate: true,
    });
  }, [fillText, invested, setValue]);

  if (wantKey === null) return null;
  if (!result || result.key !== wantKey) return `Fetching ${metal} rate…`;
  if (result.kind === "error") return result.message;
  if (!readyRate || fillText === null || invested !== autoText) return null;
  const base = `${formatINR(readyRate.rate_per_gram)}/g × ${weightNum.toFixed(3)} g (IBJA, ${formatDate(readyRate.rate_date)})`;
  return readyRate.rate_date !== readyRate.requested_date
    ? `${base}, last rate before ${formatDate(readyRate.requested_date)}`
    : base;
}

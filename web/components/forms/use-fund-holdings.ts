"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import { holdingsVersion } from "@/lib/holdings-cache";
import { isSoldHolding } from "@/lib/sip";
import type { HoldingsResponse, MutualFundItem } from "@/lib/types";

/** The few fields of an MF holding the SIP form needs to offer "Add to". */
export interface FundHolding {
  id: number;
  scheme_code: number | null;
  scheme_name: string;
  platform: string | null;
  units: number;
}

const MAX_PAGES = 50;

// One fetch of the user's MF holdings serves every fund the form picks;
// reused until a holding changes (the holdings version moves).
let cache: { version: number; items: FundHolding[] } | null = null;
let inflight: { version: number; promise: Promise<FundHolding[]> } | null = null;

async function fetchAll(): Promise<FundHolding[]> {
  const out: FundHolding[] = [];
  let pageCount = 1;
  for (let page = 1; page <= pageCount && page <= MAX_PAGES; page++) {
    const res = await apiGet<HoldingsResponse<MutualFundItem>>(`/holdings/mf?page=${page}`);
    pageCount = res.page_count;
    for (const r of res.items) {
      if (isSoldHolding(r)) continue; // "Add to" never offers a sold holding
      out.push({
        id: r.id,
        scheme_code: r.scheme_code ?? null,
        scheme_name: r.scheme_name,
        platform: r.platform ?? null,
        units: r.units,
      });
    }
  }
  return out;
}

function loadHoldings(): Promise<FundHolding[]> {
  const version = holdingsVersion("mf");
  if (cache && cache.version === version) return Promise.resolve(cache.items);
  if (inflight && inflight.version === version) return inflight.promise;
  const promise = fetchAll()
    .then((items) => {
      cache = { version, items };
      return items;
    })
    .finally(() => {
      if (inflight?.promise === promise) inflight = null;
    });
  inflight = { version, promise };
  return promise;
}

/**
 * All the user's MF holdings, loaded once when the form mounts (not per fund
 * picked). `holdings` is null while loading; `failed` is true when the load
 * errored, in which case the form simply offers no "Add to" choice.
 */
export function useFundHoldings() {
  const [holdings, setHoldings] = useState<FundHolding[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    loadHoldings()
      .then((items) => {
        if (!cancelled) {
          setHoldings(items);
          setFailed(false);
        }
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { holdings, failed };
}

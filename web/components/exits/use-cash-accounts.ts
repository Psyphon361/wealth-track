"use client";

import { useEffect, useState } from "react";
import { apiGet, toApiMessage, type ApiMessage } from "@/lib/api";
import type { CashAccount } from "@/lib/exits";
import { anyHoldingsVersion, subscribeHoldings } from "@/lib/holdings-cache";
import type { CashItem, HoldingsResponse } from "@/lib/types";

const MAX_PAGES = 20;

// One fetch shared by every user of the hook, reused until any holding changes
// (a sale or a purchase paid from an account changes its balance).
let cache: { version: number; items: CashAccount[] } | null = null;
let inflight: { version: number; promise: Promise<CashAccount[]> } | null = null;

async function fetchAccounts(): Promise<CashAccount[]> {
  const out: CashAccount[] = [];
  let pageCount = 1;
  for (let page = 1; page <= pageCount && page <= MAX_PAGES; page++) {
    const res = await apiGet<HoldingsResponse<CashItem>>(
      `/holdings/cash?sort=name&dir=asc&page=${page}`,
    );
    pageCount = res.page_count;
    for (const item of res.items) {
      if (item.status !== "active") continue;
      out.push({ id: item.id, name: item.name, balance: Number(item.balance) });
    }
  }
  return out.sort((a, b) => a.name.localeCompare(b.name));
}

function loadAccounts(): Promise<CashAccount[]> {
  const version = anyHoldingsVersion();
  if (cache && cache.version === version) return Promise.resolve(cache.items);
  if (inflight && inflight.version === version) return inflight.promise;
  const promise = fetchAccounts()
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
 * The user's active cash accounts (every page, sorted by name). `accounts` is null while
 * loading; on failure it is empty and `error` holds the API text. Reloads when holdings change.
 */
export function useCashAccounts(): {
  accounts: CashAccount[] | null;
  error: ApiMessage | null;
} {
  const [accounts, setAccounts] = useState<CashAccount[] | null>(null);
  const [error, setError] = useState<ApiMessage | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => subscribeHoldings(() => setTick((t) => t + 1)), []);

  useEffect(() => {
    let cancelled = false;
    loadAccounts()
      .then((list) => {
        if (cancelled) return;
        setAccounts(list);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(toApiMessage(err));
        setAccounts([]);
      });
    return () => {
      cancelled = true;
    };
  }, [tick]);

  return { accounts, error };
}

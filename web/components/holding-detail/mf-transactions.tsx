"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiGet, toApiMessage, type ApiMessage } from "@/lib/api";
import { dateTile } from "@/lib/bond-schedule";
import { formatINR } from "@/lib/format";
import { notify } from "@/lib/notify";
import { showMoreLabel, transactionLabel } from "@/lib/sip";
import type { MfTransaction, MfTransactionsResponse } from "@/lib/types";
import { LABEL } from "./sections";

const units = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 3,
  maximumFractionDigits: 3,
});
const nav = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
});

const listCls =
  "flex flex-col divide-y divide-border/50 overflow-hidden rounded-lg border border-border/60";

function ErrorLine({
  error,
  onRetry,
  retrying = false,
}: {
  error: ApiMessage;
  onRetry: () => void;
  retrying?: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <p className="text-[13.5px] font-medium text-destructive">
          {error.message}
        </p>
        {error.description ? (
          <p className="text-[13.2px] text-muted-foreground">
            {error.description}
          </p>
        ) : null}
      </div>
      <Button variant="outline" size="sm" onClick={onRetry} disabled={retrying}>
        {retrying ? <Loader2 className="animate-spin" aria-hidden /> : null}
        {retrying ? "Loading…" : "Retry"}
      </Button>
    </div>
  );
}

function Row({ t }: { t: MfTransaction }) {
  const tile = dateTile(t.date);
  return (
    <li className="flex items-center gap-3 px-3 py-2.5 text-[13.5px]">
      <span className="num w-11 shrink-0 rounded-md bg-muted/50 py-1 text-center leading-tight">
        <span className="block text-[13.5px] font-medium">{tile.day}</span>
        <span className="block text-[11px] text-muted-foreground">
          {tile.month} {tile.year}
        </span>
      </span>
      <span className="min-w-0 flex-1">
        <span className="block">{transactionLabel(t)}</span>
        <span className="num block truncate text-xs text-muted-foreground">
          {units.format(t.units)} units
          {t.nav !== null ? ` · NAV ${nav.format(t.nav)}` : ""}
        </span>
      </span>
      <span className="num shrink-0 text-right">{formatINR(t.amount)}</span>
    </li>
  );
}

/** Transactions of one MF holding, newest first, ten at a time. */
export function MfTransactions({ id }: { id: number }) {
  const [items, setItems] = useState<MfTransaction[] | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [error, setError] = useState<ApiMessage | null>(null);
  const [moreError, setMoreError] = useState<ApiMessage | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const requestId = useRef(0);
  const hasData = useRef(false);

  const loadFirst = useCallback(() => {
    const rid = ++requestId.current;
    apiGet<MfTransactionsResponse>(`/holdings/mf/${id}/transactions?page=1`)
      .then((res) => {
        if (rid !== requestId.current) return;
        hasData.current = true;
        setItems(res.items);
        setTotal(res.total);
        setPage(1);
        setError(null);
        setMoreError(null);
      })
      .catch((err: unknown) => {
        if (rid !== requestId.current) return;
        if (hasData.current) notify.error(err);
        else setError(toApiMessage(err));
      });
  }, [id]);

  useEffect(() => {
    const counter = requestId;
    loadFirst();
    return () => {
      counter.current++;
    };
  }, [loadFirst]);

  async function loadMore() {
    const rid = requestId.current;
    setLoadingMore(true);
    setMoreError(null);
    try {
      const res = await apiGet<MfTransactionsResponse>(
        `/holdings/mf/${id}/transactions?page=${page + 1}`,
      );
      if (rid !== requestId.current) return;
      setItems((prev) => {
        const seen = new Set((prev ?? []).map((t) => t.id));
        return [...(prev ?? []), ...res.items.filter((t) => !seen.has(t.id))];
      });
      setTotal(res.total);
      setPage(res.page);
    } catch (e) {
      if (rid === requestId.current) setMoreError(toApiMessage(e));
    } finally {
      setLoadingMore(false);
    }
  }

  const more = items ? showMoreLabel(total, items.length) : null;

  return (
    <Card size="sm" className="gap-3 px-4">
      <h3 className={LABEL}>Transactions</h3>
      {error && !items ? (
        <ErrorLine
          error={error}
          onRetry={() => {
            setError(null);
            loadFirst();
          }}
        />
      ) : !items ? (
        <div
          className="space-y-2"
          aria-busy="true"
          aria-label="Loading transactions"
        >
          <Skeleton className="h-12 rounded-lg" />
          <Skeleton className="h-12 rounded-lg" />
          <Skeleton className="h-12 rounded-lg" />
        </div>
      ) : items.length === 0 ? (
        <p className="text-[13.2px] text-muted-foreground">
          No transactions recorded for this holding yet.
        </p>
      ) : (
        <>
          <ul className={listCls}>
            {items.map((t) => (
              <Row key={t.id} t={t} />
            ))}
          </ul>
          {moreError ? (
            <ErrorLine
              error={moreError}
              onRetry={() => void loadMore()}
              retrying={loadingMore}
            />
          ) : more ? (
            <div>
              <Button
                variant="outline"
                size="sm"
                disabled={loadingMore}
                onClick={() => void loadMore()}
              >
                {loadingMore ? (
                  <Loader2 className="animate-spin" aria-hidden />
                ) : null}
                {loadingMore ? "Loading…" : more}
              </Button>
            </div>
          ) : null}
        </>
      )}
    </Card>
  );
}

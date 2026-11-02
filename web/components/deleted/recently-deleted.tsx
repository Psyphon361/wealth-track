"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { ArchiveRestore, Loader2, Trash2 } from "lucide-react";
import { AssetTypeIcon } from "@/components/asset-type-icon";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { apiGet, toApiMessage, type ApiMessage } from "@/lib/api";
import { getAssetEntry } from "@/lib/asset-catalog";
import { formatDate } from "@/lib/format";
import { anyHoldingsVersion, subscribeHoldings } from "@/lib/holdings-cache";
import { restoreHolding } from "@/lib/restore-holding";
import type { DeletedHolding } from "@/lib/types";

function DeletedRow({
  item,
  busy,
  onRestore,
}: {
  item: DeletedHolding;
  busy: boolean;
  onRestore: (item: DeletedHolding) => void;
}) {
  const entry = getAssetEntry(item.type);
  const Icon = entry?.icon ?? Trash2;
  return (
    <li
      className={`flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-3 transition-opacity ${busy ? "opacity-60" : ""}`}
    >
      <AssetTypeIcon icon={Icon} />
      <div className="min-w-0 flex-1 basis-40">
        <p className="text-[13.5px] font-medium break-words">{item.name}</p>
        <p className="text-xs text-muted-foreground">
          {item.type_label} · Deleted{" "}
          <span className="num">{formatDate(item.deleted_at)}</span>
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <span className="num text-xs text-muted-foreground">
          {item.days_left} {item.days_left === 1 ? "day" : "days"} left
        </span>
        <Button
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={() => onRestore(item)}
        >
          {busy ? (
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
          ) : (
            <ArchiveRestore aria-hidden />
          )}
          {busy ? "Restoring…" : "Restore"}
        </Button>
      </div>
    </li>
  );
}

export function RecentlyDeleted() {
  const [items, setItems] = useState<DeletedHolding[] | null>(null);
  const [error, setError] = useState<ApiMessage | null>(null);
  const [busyKeys, setBusyKeys] = useState<Set<string>>(new Set());
  const inFlight = useRef<Set<string>>(new Set());
  const [refreshing, setRefreshing] = useState(false);

  const [loadedVersion, setLoadedVersion] = useState<number | null>(null);
  const currentVersion = useSyncExternalStore(
    subscribeHoldings,
    anyHoldingsVersion,
    () => 0,
  );

  const load = useCallback(() => {
    const startedAt = anyHoldingsVersion();
    apiGet<DeletedHolding[]>("/deleted")
      .then((res) => {
        setItems(res);
        setLoadedVersion(startedAt);
        setError(null);
      })
      .catch((err: unknown) => setError(toApiMessage(err)))
      .finally(() => setRefreshing(false));
  }, []);

  // Reload on mount and on every reveal (effects re-run), and whenever any
  // holding changes while visible. Rows stay on screen during the reload.
  useEffect(() => {
    load();
    return subscribeHoldings(() => {
      setRefreshing(true);
      load();
    });
  }, [load]);

  async function handleRestore(item: DeletedHolding) {
    const key = `${item.type}-${item.id}`;
    if (inFlight.current.has(key)) return;
    inFlight.current.add(key);
    setBusyKeys(new Set(inFlight.current));
    const ok = await restoreHolding(item.type, item.id);
    inFlight.current.delete(key);
    setBusyKeys(new Set(inFlight.current));
    if (ok) {
      setItems((prev) =>
        prev
          ? prev.filter((i) => !(i.type === item.type && i.id === item.id))
          : prev,
      );
    }
  }

  if (error) {
    return (
      <div className="flex flex-col items-start gap-3 rounded-lg border border-destructive/30 p-4">
        <div>
          <p className="text-[13.5px] font-medium text-destructive">
            {error.message}
          </p>
          {error.description ? (
            <p className="text-[13.5px] text-muted-foreground">{error.description}</p>
          ) : null}
        </div>
        <Button variant="outline" onClick={load}>
          Retry
        </Button>
      </div>
    );
  }

  const isStale = loadedVersion !== null && currentVersion !== loadedVersion;

  if (!items || (isStale && items.length === 0)) {
    return (
      <div className="space-y-2">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-16 w-full" />
        ))}
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="rounded-lg border border-dashed py-12 text-center text-[13.5px] text-muted-foreground">
        No recently deleted holdings
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex h-4 items-center justify-end text-xs text-muted-foreground">
        {refreshing ? (
          <Loader2 className="size-3.5 animate-spin" aria-label="Refreshing" />
        ) : null}
      </div>
      <ul className="divide-y rounded-lg border">
        {items.map((item) => (
          <DeletedRow
            key={`${item.type}-${item.id}`}
            item={item}
            busy={busyKeys.has(`${item.type}-${item.id}`)}
            onRestore={handleRestore}
          />
        ))}
      </ul>
    </div>
  );
}

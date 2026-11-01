"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { type LucideIcon } from "lucide-react";
import { apiGet } from "@/lib/api";
import { ASSET_CATALOG, ASSET_GROUPS } from "@/lib/asset-catalog";
import { cn } from "@/lib/utils";
import type { AssetType, DashboardResponse } from "@/lib/types";

/** Display order from the catalog, one array per group (separated by a divider). */
export const TAB_GROUPS: AssetType[][] = ASSET_GROUPS.map((g) =>
  ASSET_CATALOG.filter((a) => a.group === g).map((a) => a.type),
);

export const TAB_ORDER: AssetType[] = TAB_GROUPS.flat();

export const TAB_LABELS: Record<AssetType, string> = {
  fd: "FD",
  rd: "RD",
  stock: "Stocks",
  bond: "Bonds",
  mf: "Mutual funds",
  gold: "Gold & Silver",
  cash: "Cash",
  pf: "EPF & PPF",
};

const TAB_ICONS = Object.fromEntries(
  ASSET_CATALOG.map((e) => [e.type, e.icon]),
) as Record<AssetType, LucideIcon>;

/** "Add FD", "Add RD", "Add stocks", "Add bonds", "Add mutual funds". */
export function addLabel(type: AssetType): string {
  const label = TAB_LABELS[type];
  if (type === "pf") return "Add EPF/PPF";
  const keepCase = type === "fd" || type === "rd" || type === "gold" || type === "cash";
  return `Add ${keepCase ? label : label.toLowerCase()}`;
}

type Counts = Partial<Record<AssetType, number>>;

/** Size and shape shared by the count badge and its loading placeholder. */
const COUNT_BADGE_SHAPE = "h-[18px] min-w-[18px] rounded-full";

// Last counts seen, so switching tabs doesn't flash empty counts.
let cachedCounts: Counts | null = null;

const listeners = new Set<() => void>();

/** Ask the tab bar to re-fetch its counts (after saves and deletes). */
export function refreshAssetTabCounts() {
  listeners.forEach((fn) => fn());
}

function activeFromPath(pathname: string): AssetType | null {
  const seg = pathname.split("/")[2];
  return TAB_ORDER.find((t) => t === seg) ?? null;
}

/** Grouped pill bar linking to /portfolio/{type}, one pill per asset type. */
export function AssetTabs() {
  const pathname = usePathname();
  const active = activeFromPath(pathname);
  const [counts, setCounts] = useState<Counts | null>(cachedCounts);

  useEffect(() => {
    let cancelled = false;
    function load() {
      apiGet<DashboardResponse>("/dashboard")
        .then((res) => {
          const next: Counts = {};
          for (const row of res.by_type) next[row.type] = row.count + row.matured_count;
          cachedCounts = next;
          if (!cancelled) setCounts(next);
        })
        .catch(() => {
          // Counts are decorative; the grid reports its own errors.
        });
    }
    load();
    listeners.add(load);
    return () => {
      cancelled = true;
      listeners.delete(load);
    };
  }, []);

  const pill =
    "flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[13.5px] whitespace-nowrap outline-none transition-colors focus-visible:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50";

  return (
    <nav aria-label="Asset types" className="min-w-0">
      <ul className="no-scrollbar flex items-center gap-1 overflow-x-auto p-1">
        {TAB_GROUPS.map((group, gi) => (
          <li key={gi} className="flex shrink-0 items-center gap-1">
            {gi > 0 ? (
              <span aria-hidden className="mr-1 h-5 w-px bg-border" />
            ) : null}
            {group.map((type) => {
              const isActive = type === active;
              const Icon = TAB_ICONS[type];
              const count = counts?.[type];
              return (
                <Link
                  key={type}
                  href={`/portfolio/${type}`}
                  aria-current={isActive ? "page" : undefined}
                  className={cn(
                    pill,
                    isActive
                      ? "border-border bg-muted font-medium text-foreground"
                      : "border-transparent text-muted-foreground hover:bg-muted/50 hover:text-foreground",
                  )}
                >
                  <Icon className="size-3.5" />
                  {TAB_LABELS[type]}
                  {count !== undefined ? (
                    <span
                      className={cn(
                        COUNT_BADGE_SHAPE,
                        "num inline-flex items-center justify-center bg-primary/15 px-1.5 text-[11px] leading-none font-medium text-primary",
                      )}
                    >
                      {count}
                    </span>
                  ) : (
                    <span
                      aria-hidden
                      className={cn(
                        COUNT_BADGE_SHAPE,
                        "inline-flex bg-primary/10 animate-pulse motion-reduce:animate-none",
                      )}
                    />
                  )}
                </Link>
              );
            })}
          </li>
        ))}
      </ul>
    </nav>
  );
}

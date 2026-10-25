"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { apiGet } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { AssetType, DashboardResponse } from "@/lib/types";

const TAB_ORDER: AssetType[] = ["fd", "rd", "stock", "bond", "mf"];

/** Width of every tab and of the sliding indicator, in rem. */
const TAB_WIDTH_REM = 7.5;

export const TAB_LABELS: Record<AssetType, string> = {
  fd: "FD",
  rd: "RD",
  stock: "Stocks",
  bond: "Bonds",
  mf: "Mutual Funds",
};

/** "Add FD", "Add RD", "Add stocks", "Add bonds", "Add mutual funds". */
export function addLabel(type: AssetType): string {
  const label = TAB_LABELS[type];
  return `Add ${type === "fd" || type === "rd" ? label : label.toLowerCase()}`;
}

type Counts = Partial<Record<AssetType, number>>;

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

/**
 * Tab bar linking to /portfolio/{type}. Lives in the layout so one indicator
 * slides between tabs.
 */
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
          for (const row of res.by_type) next[row.type] = row.count;
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

  const index = active ? TAB_ORDER.indexOf(active) : 0;

  return (
    <nav aria-label="Asset types" className="min-w-0 border-b">
      <ul className="relative flex overflow-x-auto">
        {TAB_ORDER.map((type) => {
          const isActive = type === active;
          const count = counts?.[type];
          return (
            <li key={type} className="shrink-0">
              <Link
                href={`/portfolio/${type}`}
                aria-current={isActive ? "page" : undefined}
                style={{ width: `${TAB_WIDTH_REM}rem` }}
                className={cn(
                  "flex items-center justify-center gap-1.5 px-2 py-2 text-sm whitespace-nowrap outline-none transition-colors focus-visible:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50",
                  isActive
                    ? "font-medium text-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {TAB_LABELS[type]}
                {count !== undefined ? (
                  <span className="num text-xs text-muted-foreground">
                    {count}
                  </span>
                ) : null}
              </Link>
            </li>
          );
        })}
        <li
          aria-hidden
          className={cn(
            "pointer-events-none absolute bottom-0 left-0 h-0.5 bg-primary transition-transform duration-300 ease-out motion-reduce:transition-none",
            active ? "opacity-100" : "opacity-0",
          )}
          style={{
            width: `${TAB_WIDTH_REM}rem`,
            transform: `translateX(${index * TAB_WIDTH_REM}rem)`,
          }}
        />
      </ul>
    </nav>
  );
}

"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronDown, TriangleAlert } from "lucide-react";
import { formatDate } from "@/lib/format";
import type { AnalyticsDataHealth, AssetType } from "@/lib/types";

interface Item {
  type: AssetType;
  id: number;
  name: string;
  date: string | null;
}

interface Group {
  key: string;
  count: number;
  summary: string;
  title: string;
  dateLabel: string;
  items: Item[];
}

function buildGroups(h: AnalyticsDataHealth): Group[] {
  const groups: Group[] = [
    {
      key: "at_cost",
      count: h.at_cost.count,
      summary: `${h.at_cost.count} valued at cost`,
      title: "Valued at cost (no price found)",
      dateLabel: "",
      items: h.at_cost.items.map((i) => ({ ...i, date: null })),
    },
    {
      key: "stale",
      count: h.stale_balances.count,
      summary: `${h.stale_balances.count} stale ${h.stale_balances.count === 1 ? "balance" : "balances"}`,
      title: "Stale balances",
      dateLabel: "as of",
      items: h.stale_balances.items.map((i) => ({ ...i, date: i.as_of })),
    },
  ];
  return groups.filter((g) => g.count > 0);
}

export function newestPriceDate(h: AnalyticsDataHealth): string | null {
  const dates = Object.values(h.latest).filter((d): d is string => !!d);
  return dates.length ? dates.reduce((a, b) => (a > b ? a : b)) : null;
}

export function DataHealthStrip({ health }: { health: AnalyticsDataHealth }) {
  const [open, setOpen] = useState(false);
  const groups = buildGroups(health);
  if (groups.length === 0) return null;

  return (
    <div className="min-w-0 rounded-md bg-amber-500/10 px-3 py-1.5 text-xs text-amber-400">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <TriangleAlert className="size-3 shrink-0" aria-hidden="true" />
        <p className="min-w-0 flex-1">
          Some figures may be off:{" "}
          <span className="num">{groups.map((g) => g.summary).join(" · ")}</span>
        </p>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs hover:text-amber-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          Details
          <ChevronDown className={`size-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
        </button>
      </div>
      {open && (
        <div className="mt-2 space-y-3 border-t border-amber-500/20 pt-2 text-foreground">
          {groups.map((g) => (
            <div key={g.key}>
              <p className="mb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                {g.title}
              </p>
              <ul className="space-y-0.5">
                {g.items.map((i) => (
                  <li key={`${i.type}-${i.id}`}>
                    <Link
                      href={`/portfolio/${i.type}/${i.id}`}
                      className="flex items-center gap-2 rounded-md px-1.5 py-1 text-[13.5px] hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <span className="min-w-0 flex-1 truncate">{i.name}</span>
                      {i.date && (
                        <span className="num shrink-0 text-xs text-muted-foreground">
                          {g.dateLabel} {formatDate(i.date)}
                        </span>
                      )}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

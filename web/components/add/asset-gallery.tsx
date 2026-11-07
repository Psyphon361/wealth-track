"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiGet } from "@/lib/api";
import { ASSET_CATALOG, ASSET_GROUPS } from "@/lib/asset-catalog";
import { reinvestNote } from "@/lib/paid-from";
import { peekReinvest } from "@/lib/reinvest";
import type { AssetType, DashboardResponse } from "@/lib/types";

export function AssetGallery() {
  const [counts, setCounts] = useState<Partial<Record<AssetType, number>>>({});
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    const p = peekReinvest();
    // Read after mount: sessionStorage does not exist during server rendering.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setNote(p ? `${reinvestNote(p)} Pick what you bought.` : null);
  }, []);

  useEffect(() => {
    let cancelled = false;
    apiGet<DashboardResponse>("/dashboard")
      .then((data) => {
        if (cancelled) return;
        const next: Partial<Record<AssetType, number>> = {};
        for (const row of data.by_type) next[row.type] = row.count;
        setCounts(next);
      })
      .catch(() => {
        // Counts are optional decoration; omit them silently on failure.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-5">
      <div>
        <h2 className="text-sm font-medium">Add a holding</h2>
        <p className="text-[13.5px] text-muted-foreground">
          Pick the kind of asset you want to record.
        </p>
      </div>
      {note ? (
        <p className="num rounded-md border border-border bg-muted/30 px-3 py-2 text-[13.2px] text-muted-foreground">
          {note}
        </p>
      ) : null}
      {ASSET_GROUPS.map((group) => (
        <section key={group} className="flex flex-col gap-2">
          <h3 className="text-[11px] font-medium tracking-wider text-muted-foreground uppercase">
            {group}
          </h3>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {ASSET_CATALOG.filter((a) => a.group === group).map((a) => {
              const count = counts[a.type];
              return (
                <Link
                  key={a.type}
                  href={`/add/${a.type}`}
                  className="flex items-center gap-3 rounded-xl sm:flex-col sm:items-stretch bg-card p-3 text-[13.5px] text-card-foreground ring-1 ring-foreground/10 transition-colors outline-none hover:bg-accent/50 hover:ring-foreground/25 focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <a.icon className="size-5" />
                  </div>
                  <div className="min-w-0 flex-1 sm:flex-none">
                    <p className="text-[13.5px] font-medium">{a.title}</p>
                    <p className="text-xs text-muted-foreground">{a.hint}</p>
                  </div>
                  <p className="num min-h-4 shrink-0 text-xs text-muted-foreground sm:mt-auto">
                    {count !== undefined ? `${count} held` : null}
                  </p>
                </Link>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}

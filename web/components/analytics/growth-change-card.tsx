"use client";

import { useState } from "react";
import { Card } from "@/components/ui/card";
import { CardInfo } from "@/components/analytics/card-info";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { formatINRWhole } from "@/lib/format";
import { MONEY_COLOR, changeSentence, dateRangeLabel, signedWhole, splitShares } from "@/lib/growth";
import type { AnalyticsGrowthPeriod } from "@/lib/types";

function tone(n: number): string {
  return n > 0 ? "text-gain" : n < 0 ? "text-loss" : "";
}

export function GrowthChangeCard({ periods }: { periods: AnalyticsGrowthPeriod[] }) {
  const [periodKey, setPeriodKey] = useState(periods[0]?.key ?? "this_month");
  const [active, setActive] = useState<string | null>(null);
  const period = periods.find((p) => p.key === periodKey) ?? periods[0];
  if (!period) return null;

  const items = periods.map((p) => ({ value: p.key, label: p.label }));
  const shares = splitShares(period.new_money, period.growth);
  const growthColor = period.growth < 0 ? "var(--loss)" : "var(--gain)";
  const rows = [
    { key: "money", label: "Your money", value: period.new_money, share: shares.money, color: MONEY_COLOR },
    { key: "growth", label: "Market growth", value: period.growth, share: shares.growth, color: growthColor },
  ];
  const dim = (key: string) =>
    active !== null && active !== key ? "opacity-40" : "opacity-100";

  return (
    <Card size="sm" className="h-full min-w-0 gap-0 px-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Net worth change
          </p>
          <CardInfo>
            How much your net worth changed in the period, split into money you put in and
            growth from markets and interest.
          </CardInfo>
        </div>
        <Select
          items={items}
          value={periodKey}
          onValueChange={(v) => setPeriodKey((v as string | null) ?? periods[0].key)}
        >
          <SelectTrigger size="sm" className="w-[8.5rem] text-xs" aria-label="Net worth change period">
            <SelectValue />
          </SelectTrigger>
          <SelectContent alignItemWithTrigger={false} className="w-(--anchor-width) min-w-0">
            {items.map((p) => (
              <SelectItem key={p.value} value={p.value}>
                {p.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="mt-3">
        <p className={`num text-2xl font-semibold leading-none ${tone(period.change)}`}>
          {signedWhole(period.change)}
        </p>
        <p className="mt-3 text-[13.5px] text-foreground">
          {changeSentence(period.new_money, period.growth)}
        </p>
        <p className="mt-2 text-[13.2px] text-muted-foreground">
          <span className="num">
            {formatINRWhole(period.start_value)} → {formatINRWhole(period.end_value)}
          </span>{" "}
          · <span className="num">{dateRangeLabel(period.start_date, period.end_date)}</span>
        </p>
      </div>
      <div
        className="mt-6 flex h-2.5 gap-0.5 overflow-hidden rounded-full"
        onMouseLeave={() => setActive(null)}
        aria-hidden="true"
      >
        {rows.map((r) =>
          r.share > 0 ? (
            <div
              key={r.key}
              onMouseEnter={() => setActive(r.key)}
              className={`h-full rounded-full transition-opacity duration-150 ${dim(r.key)}`}
              style={{ width: `${r.share}%`, minWidth: 2, backgroundColor: r.color }}
            />
          ) : null,
        )}
      </div>
      <ul className="mt-4 flex flex-col gap-0.5" onMouseLeave={() => setActive(null)}>
        {rows.map((r) => (
          <li
            key={r.key}
            onMouseEnter={() => setActive(r.key)}
            className={`flex items-center gap-2 rounded-md px-1.5 py-1.5 text-[13.5px] transition-[opacity,background-color] duration-150 hover:bg-muted/40 ${dim(r.key)}`}
          >
            <span
              className="size-2 shrink-0 rounded-full"
              style={{ backgroundColor: r.color }}
              aria-hidden="true"
            />
            <span className="min-w-0 flex-1 truncate">{r.label}</span>
            <span className={`num shrink-0 text-right ${r.key === "growth" ? tone(r.value) : ""}`}>
              {signedWhole(r.value)}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

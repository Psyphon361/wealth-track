"use client";

import { useState } from "react";
import { Card } from "@/components/ui/card";
import { CardInfo } from "@/components/analytics/card-info";
import { MONEY_COLOR, columnLabel, monthColumns, monthLabel, signedWhole } from "@/lib/growth";
import type { AnalyticsGrowthMonth } from "@/lib/types";

function tone(n: number): string {
  return n > 0 ? "text-gain" : n < 0 ? "text-loss" : "";
}

function Dot({ color }: { color: string }) {
  return (
    <span
      className="size-2 shrink-0 rounded-full"
      style={{ backgroundColor: color }}
      aria-hidden="true"
    />
  );
}

export function GrowthMonthsCard({ months }: { months: AnalyticsGrowthMonth[] }) {
  const { columns, zero } = monthColumns(months);
  const newest = columns[columns.length - 1]?.month ?? null;
  const [picked, setPicked] = useState<string | null>(null);
  const activeMonth = picked ?? newest;
  const activeData = months.find((m) => m.month === activeMonth);
  const growthColor = activeData && activeData.growth < 0 ? "var(--loss)" : "var(--gain)";

  return (
    <Card size="sm" className="h-full min-w-0 justify-between gap-4 px-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Month by month
          </p>
          <CardInfo>
            The same split for each of the last 12 months: money you put in or took out, and
            growth from markets and interest.
          </CardInfo>
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <Dot color={MONEY_COLOR} />
            Your money
          </span>
          <span className="flex items-center gap-1.5">
            <Dot color="var(--gain)" />
            Market growth
          </span>
        </div>
      </div>
      <div className="mt-2 flex gap-1.5" onMouseLeave={() => setPicked(null)}>
        {columns.map((c, i) => {
          const label = columnLabel(c.month, i === 0);
          const dim = activeMonth !== c.month ? "opacity-55" : "opacity-100";
          return (
            <button
              key={c.month}
              type="button"
              onMouseEnter={() => setPicked(c.month)}
              onClick={() => setPicked(c.month)}
              onFocus={() => setPicked(c.month)}
              aria-label={`Show ${c.month}`}
              className="flex min-w-0 flex-1 flex-col items-stretch gap-2.5 rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <div className={`relative h-[180px] transition-opacity duration-150 lg:h-[220px] ${dim}`}>
                <span
                  className="absolute inset-x-0 h-px bg-border/50"
                  style={{ bottom: `${zero}%` }}
                  aria-hidden="true"
                />
                {c.segments.map((s) =>
                  s.height > 0 ? (
                    <span
                      key={s.kind}
                      className={`absolute inset-x-[15%] ${s.value < 0 ? "rounded-b-[4px]" : "rounded-t-[4px]"}`}
                      style={{
                        bottom: `calc(${s.bottom}% + 1px)`,
                        height: `max(2px, calc(${s.height}% - 2px))`,
                        backgroundColor:
                          s.kind === "money"
                            ? MONEY_COLOR
                            : s.value < 0
                              ? "var(--loss)"
                              : "var(--gain)",
                      }}
                      aria-hidden="true"
                    />
                  ) : null,
                )}
              </div>
              <span className="flex h-6 flex-col items-center text-[10.5px] leading-tight text-muted-foreground">
                <span>{label.month}</span>
                {label.year !== null && <span className="num opacity-70">{label.year}</span>}
              </span>
            </button>
          );
        })}
      </div>
      {activeData && (
        <div
          className="mt-1 flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5 border-t border-border/50 pt-3 text-[13.5px]"
          aria-live="polite"
        >
          <span className="font-medium">{monthLabel(activeData.month)}</span>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <span className="flex items-center gap-1.5">
              <Dot color={MONEY_COLOR} />
              <span className="text-muted-foreground">Your money</span>
              <span className="num">{signedWhole(activeData.new_money)}</span>
            </span>
            <span className="flex items-center gap-1.5">
              <Dot color={growthColor} />
              <span className="text-muted-foreground">Market growth</span>
              <span className={`num ${tone(activeData.growth)}`}>
                {signedWhole(activeData.growth)}
              </span>
            </span>
          </div>
        </div>
      )}
    </Card>
  );
}

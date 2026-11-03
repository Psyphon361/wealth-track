"use client";

import { useState } from "react";
import { Card } from "@/components/ui/card";
import { formatINR, formatPct } from "@/lib/format";
import type { AnalyticsLiquidity } from "@/lib/types";

const COLORS: Record<string, string> = {
  instant: "oklch(0.8 0.17 150)",
  days: "oklch(0.7 0.15 150)",
  breakable: "oklch(0.58 0.12 150)",
  illiquid: "oklch(0.46 0.09 150)",
  locked: "oklch(0.35 0.06 150)",
  not_classified: "oklch(0.5 0 0)",
};

const HINTS: Record<string, string> = {
  instant: "Cash and savings",
  days: "Stocks, MF, digital gold",
  breakable: "FD and RD · ~1% penalty",
  illiquid: "Bonds, physical gold",
  locked: "EPF, PPF, NPS, ELSS lock-in",
  not_classified: "Other assets",
};

export function LiquidityCard({ liquidity }: { liquidity: AnalyticsLiquidity }) {
  const [active, setActive] = useState<string | null>(null);
  const buckets = liquidity.buckets.filter((b) => b.amount > 0);
  const quick = liquidity.buckets
    .filter((b) => b.key === "instant" || b.key === "days")
    .reduce((s, b) => ({ amount: s.amount + b.amount, percent: s.percent + b.percent }), {
      amount: 0,
      percent: 0,
    });
  const dim = (key: string) =>
    active !== null && active !== key ? "opacity-40" : "opacity-100";

  return (
    <Card size="sm" className="min-w-0 gap-3 px-4">
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        Liquidity
      </p>
      <div className="mt-3">
        <p className="num text-xl font-semibold">{formatINR(quick.amount)}</p>
        <p className="text-[13.2px] text-muted-foreground">
          available within 3 days ·{" "}
          <span className="num">{formatPct(quick.percent)}</span> of your portfolio
        </p>
      </div>
      {buckets.length > 0 && (
        <>
          <div className="mt-5 flex h-2.5 gap-0.5" onMouseLeave={() => setActive(null)}>
            {buckets.map((b) => (
              <div
                key={b.key}
                onMouseEnter={() => setActive(b.key)}
                className={`h-full rounded-full transition-opacity duration-150 ${dim(b.key)}`}
                style={{
                  width: `${Math.max(0, b.percent)}%`,
                  minWidth: 2,
                  backgroundColor: COLORS[b.key] ?? COLORS.not_classified,
                }}
                aria-hidden="true"
              />
            ))}
          </div>
          <ul className="mt-6 flex flex-col"onMouseLeave={() => setActive(null)}>
            {buckets.map((b) => (
              <li
                key={b.key}
                onMouseEnter={() => setActive(b.key)}
                className={`flex items-center gap-2 rounded-md px-1.5 py-1.5 text-[13.5px] transition-[opacity,background-color] duration-150 hover:bg-muted/40 ${dim(b.key)}`}
              >
                <span
                  className="size-2 shrink-0 rounded-full"
                  style={{ backgroundColor: COLORS[b.key] ?? COLORS.not_classified }}
                  aria-hidden="true"
                />
                <span className="min-w-0 flex-1 truncate">
                  {b.label}
                  <span className="ml-2 text-xs text-muted-foreground">{HINTS[b.key]}</span>
                </span>
                <span className="num shrink-0 text-right">{formatINR(b.amount)}</span>
                <span className="num w-14 shrink-0 text-right text-muted-foreground">
                  {formatPct(b.percent)}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}

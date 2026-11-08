"use client";

import { useState } from "react";
import { Card } from "@/components/ui/card";
import { CardInfo } from "@/components/analytics/card-info";
import { formatINRWhole } from "@/lib/format";
import { CLASS_COLORS } from "@/lib/analytics";
import { bucketNotes, rateText, type CapitalGains } from "@/lib/capital-gains";
import { TopProgress } from "./top-progress";
import { gainClass } from "./gains-summary";

const PALETTE = [
  CLASS_COLORS.equity,
  CLASS_COLORS.debt,
  CLASS_COLORS.gold,
  CLASS_COLORS.cash,
  CLASS_COLORS.hybrid,
  CLASS_COLORS.other,
];

export function GainsBucketsCard({
  data,
  switching,
}: {
  data: CapitalGains;
  switching: boolean;
}) {
  const [active, setActive] = useState<string | null>(null);
  const rows = data.buckets.map((b, i) => ({ b, color: PALETTE[i % PALETTE.length] }));
  const total = rows.reduce((s, r) => s + r.b.net, 0);
  const positive = rows.filter((r) => r.b.net > 0);
  const positiveTotal = positive.reduce((s, r) => s + r.b.net, 0);
  const dim = (key: string) => (active !== null && active !== key ? "opacity-40" : "opacity-100");

  return (
    <Card size="sm" className="relative min-w-0 gap-3 px-4">
      <TopProgress active={switching} />
      <div className="flex items-center gap-1.5">
        <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Gains By Type Of Tax
        </p>
        <CardInfo>
          Each kind of gain is taxed at its own rate. Losses are first set off against gains of the
          same kind where the rules allow it.
        </CardInfo>
      </div>
      <div className="mt-3">
        <p className={`num text-xl font-semibold ${gainClass(total)}`}>{formatINRWhole(total)}</p>
        <p className="text-[13.2px] text-muted-foreground">
          net gain · <span className="num">{formatINRWhole(data.summary.fixed_rate_tax)}</span> tax
          at fixed rates
        </p>
      </div>
      {rows.length > 0 && (
        <div className={`transition-opacity duration-200 ${switching ? "opacity-50" : ""}`}>
          {positiveTotal > 0 && (
            <div className="mt-5 flex h-2.5 gap-0.5" onMouseLeave={() => setActive(null)}>
              {positive.map(({ b, color }) => (
                <div
                  key={b.key}
                  onMouseEnter={() => setActive(b.key)}
                  className={`h-full rounded-full transition-opacity duration-150 ${dim(b.key)}`}
                  style={{
                    width: `${(b.net / positiveTotal) * 100}%`,
                    minWidth: 2,
                    backgroundColor: color,
                  }}
                  aria-hidden="true"
                />
              ))}
            </div>
          )}
          <div className="mt-6 flex items-center gap-2 px-1.5 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            <span className="size-2 shrink-0" aria-hidden="true" />
            <span className="min-w-0 flex-1" />
            <span className="shrink-0 text-right">Gain</span>
            <span className="w-20 shrink-0 text-right">Tax</span>
          </div>
          <ul className="flex flex-col" onMouseLeave={() => setActive(null)}>
            {rows.map(({ b, color }) => {
              const note = bucketNotes(b, Number(data.fy_start.slice(0, 4)));
              return (
                <li
                  key={b.key}
                  onMouseEnter={() => setActive(b.key)}
                  className={`flex items-center gap-2 rounded-md px-1.5 py-1.5 text-[13.5px] transition-[opacity,background-color] duration-150 hover:bg-muted/40 ${dim(b.key)}`}
                >
                  <span
                    className="size-2 shrink-0 rounded-full"
                    style={{ backgroundColor: color }}
                    aria-hidden="true"
                  />
                  <span className="min-w-0 flex-1 truncate">
                    {b.label}
                    <span className="ml-2 text-xs text-muted-foreground">{rateText(b)}</span>
                    {note.short && (
                      <span className="ml-2 text-xs text-muted-foreground">· {note.short}</span>
                    )}
                  </span>
                  {note.long && <CardInfo>{note.long}</CardInfo>}
                  <span className={`num shrink-0 text-right ${gainClass(b.net)}`}>
                    {formatINRWhole(b.net)}
                  </span>
                  <span className="num w-20 shrink-0 text-right text-muted-foreground">
                    {b.tax === null ? "Slab" : formatINRWhole(b.tax)}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </Card>
  );
}

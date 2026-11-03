"use client";

import { useState } from "react";
import { Card } from "@/components/ui/card";
import { formatDate } from "@/lib/format";
import { MONEY_COLOR } from "@/lib/growth";
import { compareFootnote, compareRows, compareSentence, pct1, returnBars } from "@/lib/returns";
import type { ReturnsBenchmark } from "@/lib/types";

const NEUTRAL = "oklch(0.55 0.02 250)";

export function ReturnsCompareCard({ benchmark }: { benchmark: ReturnsBenchmark | null }) {
  const [active, setActive] = useState<string | null>(null);
  const dim = (key: string) => (active !== null && active !== key ? "opacity-40" : "opacity-100");
  const rows = compareRows(benchmark);
  const bars = returnBars(rows.map((r) => r.value));
  const sentence = compareSentence(benchmark);

  return (
    <Card size="sm" className="h-full min-w-0 justify-between gap-4 px-4">
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        How you compare
      </p>
      {!benchmark || rows.length === 0 ? (
        <p className="text-[13.5px] text-muted-foreground">
          Comparison isn&apos;t available right now.
        </p>
      ) : (
        <>
          <p className="mt-2 text-[13.5px] text-foreground">
            {sentence ?? "Here is how your returns line up with common yardsticks."}
          </p>
          <ul className="flex flex-col gap-0.5" onMouseLeave={() => setActive(null)}>
            {rows.map((r, i) => {
              const b = bars[i];
              return (
                <li
                  key={r.key}
                  onMouseEnter={() => setActive(r.key)}
                  className={`grid grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_3.5rem] items-center gap-3 rounded-md px-1.5 py-1.5 text-[13.5px] transition-[opacity,background-color] duration-150 hover:bg-muted/40 ${dim(r.key)}`}
                >
                  <span className="min-w-0">
                    <span className="block truncate">{r.label}</span>
                    {r.note && (
                      <span className="block truncate text-[11px] text-muted-foreground">
                        {r.note}
                      </span>
                    )}
                  </span>
                  <span className="relative h-2.5" aria-hidden="true">
                    {b && (
                      <>
                        <span
                          className="absolute inset-y-0 w-px bg-border"
                          style={{ left: `${b.zero}%` }}
                        />
                        <span
                          className="absolute inset-y-0 rounded-full"
                          style={{
                            left: `${b.left}%`,
                            width: `${b.width}%`,
                            minWidth: b.width === 0 ? 0 : 2,
                            backgroundColor: r.key === "you" ? MONEY_COLOR : NEUTRAL,
                          }}
                        />
                      </>
                    )}
                  </span>
                  <span className="num text-right">{pct1(r.value)}</span>
                </li>
              );
            })}
          </ul>
          <p className="text-xs text-muted-foreground">{compareFootnote(benchmark, formatDate)}</p>
        </>
      )}
    </Card>
  );
}

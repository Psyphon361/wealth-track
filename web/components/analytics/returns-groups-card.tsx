"use client";

import { useState } from "react";
import { Card } from "@/components/ui/card";
import { CardInfo } from "@/components/analytics/card-info";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  groupDetail,
  overallHeadline,
  overallSentence,
  returnBars,
  signedPct1,
  sinceLabel,
} from "@/lib/returns";
import type { ReturnGroup } from "@/lib/types";

const VIEWS = [
  { value: "type", label: "By Type" },
  { value: "class", label: "By Asset Class" },
];

function tone(n: number): string {
  return n > 0 ? "text-gain" : n < 0 ? "text-loss" : "";
}

export function ReturnsGroupsCard({
  overall,
  byClass,
  byType,
}: {
  overall: ReturnGroup | null;
  byClass: ReturnGroup[];
  byType: ReturnGroup[];
}) {
  const [view, setView] = useState("type");
  const [picked, setPicked] = useState<string | null>(null);
  const groups = (view === "class" ? byClass : byType).filter((g) => g.return_pct !== null);
  const bars = returnBars(groups.map((g) => g.return_pct));
  const activeKey = picked ?? groups[0]?.key ?? null;
  const activeGroup = groups.find((g) => g.key === activeKey);
  const dim = (key: string) => (activeKey !== key ? "opacity-55" : "opacity-100");
  const headline = overall ? overallHeadline(overall) : null;

  return (
    <Card size="sm" className="min-w-0 gap-0 px-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Your returns
          </p>
          <CardInfo>
            Your yearly return (XIRR), worked out from when you actually invested. Holdings held
            for under a year show a simple return instead.
          </CardInfo>
        </div>
        <Select
          items={VIEWS}
          value={view}
          onValueChange={(v) => {
            setView((v as string | null) ?? "type");
            setPicked(null);
          }}
        >
          <SelectTrigger size="sm" className="w-[9.5rem] text-xs" aria-label="Returns view">
            <SelectValue />
          </SelectTrigger>
          <SelectContent alignItemWithTrigger={false} className="w-(--anchor-width) min-w-0">
            {VIEWS.map((v) => (
              <SelectItem key={v.value} value={v.value}>
                {v.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="mt-3">
        {overall && headline ? (
          <>
            <p className={`num text-2xl font-semibold leading-none ${tone(overall.return_pct ?? 0)}`}>
              {headline.value}{" "}
              <span className="text-[15.4px] font-normal text-muted-foreground">
                {headline.suffix}
              </span>
            </p>
            <p className="mt-3 text-[13.5px] text-foreground">{overallSentence(overall)}</p>
            <p className="mt-2 text-[13.2px] text-muted-foreground">{sinceLabel(overall.since)}</p>
          </>
        ) : (
          <p className="text-[13.5px] text-muted-foreground">Not enough data to compute a return.</p>
        )}
      </div>
      {groups.length > 0 && (
        <>
          <ul className="mt-6 flex flex-col gap-0.5" onMouseLeave={() => setPicked(null)}>
            {groups.map((g, i) => {
              const b = bars[i];
              const pct = g.return_pct as number;
              return (
                <li key={g.key}>
                  <button
                    type="button"
                    onMouseEnter={() => setPicked(g.key)}
                    onFocus={() => setPicked(g.key)}
                    onClick={() => setPicked(g.key)}
                    className={`grid w-full grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_3.5rem] items-center gap-3 rounded-md px-1.5 py-1.5 text-left text-[13.5px] outline-none transition-[opacity,background-color] duration-150 hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring ${dim(g.key)}`}
                  >
                    <span className="truncate">{g.label}</span>
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
                              backgroundColor: pct < 0 ? "var(--loss)" : "var(--gain)",
                            }}
                          />
                        </>
                      )}
                    </span>
                    <span className={`num text-right ${tone(pct)}`}>{signedPct1(pct)}</span>
                  </button>
                </li>
              );
            })}
          </ul>
          {activeGroup && (
            <div
              className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-border/50 pt-3 text-[13.5px]"
              aria-live="polite"
            >
              <span className="font-medium">{activeGroup.label}</span>
              <span className="num text-muted-foreground">{groupDetail(activeGroup)}</span>
            </div>
          )}
        </>
      )}
    </Card>
  );
}

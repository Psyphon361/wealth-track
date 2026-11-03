"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronDown } from "lucide-react";
import { Card } from "@/components/ui/card";
import { CardInfo } from "@/components/analytics/card-info";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { formatDate, formatINR, formatPct } from "@/lib/format";
import type { AnalyticsComingUp } from "@/lib/types";

type Period = "30d" | "90d" | "180d" | "12m";

const PERIODS: { value: Period; label: string }[] = [
  { value: "30d", label: "Next 30 Days" },
  { value: "90d", label: "Next 90 Days" },
  { value: "180d", label: "Next 180 Days" },
  { value: "12m", label: "Next 1 Year" },
];

const WINDOW_KEYS = {
  "30d": "next_30_days",
  "90d": "next_90_days",
  "180d": "next_180_days",
  "12m": "next_12_months",
} as const;

const TYPE_LABELS: Record<string, string> = {
  fd: "FD",
  rd: "RD",
  bond: "Bond",
  pf: "PPF",
};

const rowCls =
  "flex items-center gap-3 px-3 py-2.5 text-[13.5px] transition-colors hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring";

const listCls =
  "flex flex-col divide-y divide-border/50 overflow-hidden rounded-lg border border-border/60";

function DateBlock({ iso }: { iso: string | null }) {
  if (!iso) return <span className="w-11 shrink-0" aria-hidden="true" />;
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  const month = new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", {
    month: "short",
    timeZone: "UTC",
  });
  return (
    <span className="num w-11 shrink-0 rounded-md bg-muted/50 py-1 text-center leading-tight">
      <span className="block text-[13.5px] font-medium">{d}</span>
      <span className="block text-[11px] text-muted-foreground">
        {month} {String(y).slice(2)}
      </span>
    </span>
  );
}

export function ComingUpCard({ comingUp }: { comingUp: AnalyticsComingUp }) {
  const [period, setPeriod] = useState<Period>("90d");
  const [showMatured, setShowMatured] = useState(false);
  const window = comingUp[WINDOW_KEYS[period]];
  const matured = comingUp.already_matured;
  const count = window.rows.length;

  return (
    <Card size="sm" className="h-full min-w-0 gap-3 px-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Coming up
          </p>
          <CardInfo>
            Deposits and bonds maturing soon and the amount you&apos;ll receive, plus any that
            have already matured.
          </CardInfo>
        </div>
        <Select
          items={PERIODS}
          value={period}
          onValueChange={(v) => setPeriod((v as Period | null) ?? "90d")}
        >
          <SelectTrigger size="sm" className="w-[8.5rem] text-xs" aria-label="Coming up period">
            <SelectValue />
          </SelectTrigger>
          <SelectContent alignItemWithTrigger={false} className="w-(--anchor-width) min-w-0">
            {PERIODS.map((p) => (
              <SelectItem key={p.value} value={p.value}>
                {p.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="mt-3">
        <p className="num text-xl font-semibold">{formatINR(window.total)}</p>
        {count > 0 && (
          <p className="text-[13.2px] text-muted-foreground">
            <span className="num">{count}</span> {count === 1 ? "maturity" : "maturities"} by{" "}
            <span className="num">{formatDate(window.until)}</span>
          </p>
        )}
      </div>
      {count === 0 ? (
        <p className="text-[13.2px] text-muted-foreground">Nothing matures in this period</p>
      ) : (
        <ul className={`mt-3 ${listCls}`}>
          {window.rows.map((r) => (
            <li key={`${r.type}-${r.id}`}>
              <Link href={`/portfolio/${r.type}/${r.id}`} className={rowCls}>
                <DateBlock iso={r.maturity_date} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{r.name}</span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {TYPE_LABELS[r.type] ?? r.type} ·{" "}
                    <span className="num">{formatPct(r.rate)}</span>
                    {r.approximate ? " · ~ approximate" : ""}
                  </span>
                </span>
                <span className="num shrink-0 text-right">{formatINR(r.amount)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {matured.count > 0 && (
        <div>
          <button
            type="button"
            onClick={() => setShowMatured((o) => !o)}
            aria-expanded={showMatured}
            className="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <span className="num">{matured.count}</span> already matured
            <ChevronDown
              className={`size-3.5 transition-transform ${showMatured ? "rotate-180" : ""}`}
            />
          </button>
          {showMatured && (
            <ul className={`mt-1.5 ${listCls}`}>
              {matured.rows.map((r) => (
                <li key={`${r.type}-${r.id}`}>
                  <Link href={`/portfolio/${r.type}/${r.id}`} className={rowCls}>
                    <DateBlock iso={r.maturity_date} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate">{r.name}</span>
                      <span className="block truncate text-xs text-muted-foreground">
                        {TYPE_LABELS[r.type] ?? r.type}
                      </span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}

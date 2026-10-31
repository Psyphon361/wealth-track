"use client";

import { useEffect, useState } from "react";
import { Area, AreaChart, CartesianGrid, Line, XAxis, YAxis } from "recharts";
import { Card } from "@/components/ui/card";
import {
  ChartContainer,
  ChartTooltip,
  type ChartConfig,
} from "@/components/ui/chart";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { apiGet, toApiMessage } from "@/lib/api";
import { formatDate, formatINR, formatINRCompact } from "@/lib/format";
import type { NetWorthHistory, NetWorthRange } from "@/lib/types";

const RANGES: { value: NetWorthRange; label: string }[] = [
  { value: "1m", label: "1M" },
  { value: "6m", label: "6M" },
  { value: "1y", label: "1Y" },
  { value: "all", label: "All" },
];

const config = {
  current: { label: "Current", color: "var(--chart-1)" },
  invested: { label: "Invested", color: "var(--muted-foreground)" },
} satisfies ChartConfig;

/** YYYY-MM-DD -> "12 Mar" or "Mar 25" without timezone shift. */
function tickLabel(iso: string, range: NetWorthRange): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  if (range === "1m") {
    return dt.toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      timeZone: "UTC",
    });
  }
  const mon = dt.toLocaleDateString("en-GB", { month: "short", timeZone: "UTC" });
  return `${mon} ${String(y).slice(2)}`;
}

type State = {
  data: NetWorthHistory | null;
  error: { message: string; description: string } | null;
  loading: boolean;
};

export function NetWorthChart() {
  const [range, setRange] = useState<NetWorthRange>("1y");
  const [state, setState] = useState<State>({
    data: null,
    error: null,
    loading: true,
  });

  useEffect(() => {
    let cancelled = false;
    apiGet<NetWorthHistory>(`/networth/history?range=${range}`)
      .then((data) => {
        if (!cancelled) setState({ data, error: null, loading: false });
      })
      .catch((err: unknown) => {
        if (!cancelled)
          setState((s) => ({
            data: s.data,
            error: toApiMessage(err),
            loading: false,
          }));
      });
    return () => {
      cancelled = true;
    };
  }, [range]);

  const { data, error, loading } = state;
  const shown = data;

  return (
    <Card size="sm" className="px-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] font-medium tracking-wider text-muted-foreground uppercase">
          Net worth
        </p>
        <ToggleGroup
          size="sm"
          variant="outline"
          spacing={0}
          value={[range]}
          onValueChange={(v) => {
            const next = v[0] as NetWorthRange | undefined;
            if (next && next !== range) {
              setState((s) => ({ ...s, error: null, loading: true }));
              setRange(next);
            }
          }}
          aria-label="Range"
        >
          {RANGES.map((r) => (
            <ToggleGroupItem key={r.value} value={r.value} className="text-xs">
              {r.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>

      {!shown && loading ? (
        <Skeleton className="h-[220px] rounded-lg" />
      ) : error ? (
        <div>
          <p className="text-sm font-medium text-destructive">{error.message}</p>
          {error.description && (
            <p className="text-xs text-muted-foreground">{error.description}</p>
          )}
        </div>
      ) : shown && shown.points.length === 0 ? (
        <p className="py-16 text-center text-sm text-muted-foreground">
          No history yet
        </p>
      ) : shown ? (
        <div className={loading ? "opacity-60 transition-opacity" : undefined}>
          <ChartContainer config={config} className="h-[220px] w-full">
            <AreaChart
              data={shown.points}
              margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
            >
              <CartesianGrid vertical={false} strokeOpacity={0.4} />
              <XAxis
                dataKey="date"
                tickLine={false}
                axisLine={false}
                tickMargin={8}
                minTickGap={48}
                tickFormatter={(v: string) => tickLabel(v, shown.range)}
              />
              <YAxis
                width={56}
                tickLine={false}
                axisLine={false}
                tickCount={4}
                tickFormatter={(v: number) => formatINRCompact(v)}
              />
              <ChartTooltip
                cursor={false}
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const p = payload[0].payload as {
                    date: string;
                    current: number;
                    invested: number;
                  };
                  return (
                    <div className="grid gap-1 rounded-lg border bg-popover px-2.5 py-1.5 text-xs shadow-md">
                      <p className="font-medium">{formatDate(p.date)}</p>
                      <div className="flex justify-between gap-4">
                        <span className="text-muted-foreground">Current</span>
                        <span className="num">{formatINR(p.current)}</span>
                      </div>
                      <div className="flex justify-between gap-4">
                        <span className="text-muted-foreground">Invested</span>
                        <span className="num">{formatINR(p.invested)}</span>
                      </div>
                    </div>
                  );
                }}
              />
              <Area
                dataKey="current"
                type="monotone"
                stroke="var(--color-current)"
                strokeWidth={1.5}
                fill="var(--color-current)"
                fillOpacity={0.12}
                isAnimationActive={false}
              />
              <Line
                dataKey="invested"
                type="monotone"
                stroke="var(--color-invested)"
                strokeWidth={1}
                strokeDasharray="4 3"
                dot={false}
                isAnimationActive={false}
              />
            </AreaChart>
          </ChartContainer>
          {shown.stocks_at_cost_before && (
            <p className="text-xs text-muted-foreground">
              Stocks valued at cost before {formatDate(shown.stocks_at_cost_before)}
            </p>
          )}
        </div>
      ) : null}
    </Card>
  );
}

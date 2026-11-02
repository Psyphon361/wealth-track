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
import { Loader2 } from "lucide-react";
import { toApiMessage } from "@/lib/api";
import { formatDateShortMonth as formatDate } from "@/lib/chart-ticks";
import { pickTicks, tickLabel } from "@/lib/chart-ticks";
import { formatINR, formatINRCompact } from "@/lib/format";
import {
  getCachedNetWorth,
  loadNetWorth,
  prefetchNetWorth,
  subscribeNetWorth,
} from "@/lib/networth-cache";
import { chartDomain, rangeGrowth } from "@/lib/networth-range";
import { cn } from "@/lib/utils";
import { gainTone } from "@/components/portfolio/grid/gain-cell";
import type {
  DashboardResponse,
  NetWorthHistory,
  NetWorthRange,
} from "@/lib/types";
import { SummaryStats } from "./summary-cards";

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

type ErrorState = {
  range: NetWorthRange;
  message: string;
  description: string;
} | null;

export function NetWorthChart({ data }: { data: DashboardResponse }) {
  const [range, setRange] = useState<NetWorthRange>("1y");
  const [last, setLast] = useState<NetWorthHistory | null>(null);
  const [errorState, setErrorState] = useState<ErrorState>(null);
  const [, setVersion] = useState(0);

  useEffect(
    () => subscribeNetWorth(() => setVersion((v) => v + 1)),
    [],
  );

  const cached = getCachedNetWorth(range) ?? null;
  // Remember the last chart shown so it stays (dimmed) while a new range loads.
  if (cached && cached !== last) setLast(cached);

  const hasCached = cached !== null;
  const version = cached; // changes when the cache entry is replaced

  useEffect(() => {
    let cancelled = false;
    loadNetWorth(range)
      .then(() => {
        if (!cancelled) setErrorState(null);
      })
      .catch((err: unknown) => {
        if (!cancelled) setErrorState({ range, ...toApiMessage(err) });
      });
    return () => {
      cancelled = true;
    };
    // Re-run when the cache entry for this range appears or is cleared.
  }, [range, hasCached, version]);

  useEffect(() => {
    if (hasCached) {
      void prefetchNetWorth(RANGES.map((r) => r.value));
    }
  }, [hasCached]);

  const shown = cached ?? last;
  const error = !cached && errorState?.range === range ? errorState : null;
  const loading = !cached && !error;

  const lastPoint = shown?.points[shown.points.length - 1];
  const up = !lastPoint || lastPoint.current >= lastPoint.invested;
  const growth = cached ? rangeGrowth(cached.points) : null;
  const growthTone = growth === null ? "" : gainTone(growth);
  const rangeLabel = RANGES.find((r) => r.value === range)?.label ?? "";

  return (
    <Card size="sm" className="px-4" aria-busy={loading}>
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
            if (next && next !== range) setRange(next);
          }}
          aria-label="Range"
        >
          {RANGES.map((r) => (
            <ToggleGroupItem key={r.value} value={r.value} className="text-xs">
              {r.label}
              {loading && r.value === range && (
                <Loader2 className="size-3 animate-spin" />
              )}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>

      <p className="num text-2xl font-semibold whitespace-nowrap">
        {formatINR(data.total_current)}
      </p>

      <SummaryStats data={data} />

      {loading ? (
        <Skeleton className="h-4 w-32" />
      ) : growth !== null ? (
        <p className="text-xs whitespace-nowrap text-muted-foreground">
          Growth ({rangeLabel}){" "}
          <span className={cn("num font-medium", growthTone)}>
            {growth > 0 ? "+" : ""}
            {formatINR(growth)}
          </span>
        </p>
      ) : null}

      {!shown && loading ? (
        <Skeleton className="h-[220px] rounded-lg" />
      ) : error ? (
        <div>
          <p className="text-[13.5px] font-medium text-destructive">{error.message}</p>
          {error.description && (
            <p className="text-xs text-muted-foreground">{error.description}</p>
          )}
        </div>
      ) : shown && shown.points.length === 0 ? (
        <p className="py-16 text-center text-[13.5px] text-muted-foreground">
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
                ticks={pickTicks(
                  shown.points.map((p) => p.date),
                  shown.range,
                )}
                interval={shown.range === "1m" ? "preserveEnd" : 0}
                tickFormatter={(v: string) => tickLabel(v, shown.range)}
              />
              <YAxis
                width={56}
                tickLine={false}
                axisLine={false}
                tickCount={4}
                domain={chartDomain(shown.points)}
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
                dataKey={(p: { invested: number; current: number }) => [
                  p.invested,
                  p.current,
                ]}
                type="monotone"
                stroke="none"
                fill={up ? "var(--gain)" : "var(--loss)"}
                fillOpacity={0.15}
                activeDot={false}
                isAnimationActive={false}
              />
              <Line
                dataKey="current"
                type="monotone"
                stroke="var(--color-current)"
                strokeWidth={1.5}
                dot={false}
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
        </div>
      ) : null}
    </Card>
  );
}

import { TrendingDown, TrendingUp } from "lucide-react";
import { Card } from "@/components/ui/card";
import { formatDate, formatINR, formatPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { DashboardResponse } from "@/lib/types";
import { gainTone } from "@/components/portfolio/grid/gain-cell";

function Label({ children }: { children: string }) {
  return (
    <p className="text-[11px] font-medium tracking-wider text-muted-foreground uppercase">
      {children}
    </p>
  );
}

function DayChangeCard({ data }: { data: DashboardResponse }) {
  const change = data.day_change;
  const pct = data.day_change_pct;
  const asOf = data.day_change_as_of;
  const tone = change === null ? "text-foreground" : gainTone(change);
  const sign = change !== null && change > 0 ? "+" : "";
  const Icon = change !== null && change < 0 ? TrendingDown : TrendingUp;

  return (
    <Card size="sm" className="px-4">
      <Label>1-day change</Label>
      <div className="flex flex-wrap items-baseline gap-x-2">
        <p
          className={cn(
            "num text-lg font-semibold whitespace-nowrap lg:text-xl",
            tone,
          )}
        >
          {change === null ? (
            "—"
          ) : (
            <>
              {sign}
              {formatINR(change)}
            </>
          )}
        </p>
        {change !== null && pct !== null ? (
          <p className={cn("num flex items-center gap-1 text-xs", tone)}>
            {change !== 0 ? <Icon className="size-3" aria-hidden /> : null}
            {sign}
            {formatPct(pct)}
          </p>
        ) : null}
      </div>
      {change !== null && asOf ? (
        <p className="-mt-1 text-xs text-muted-foreground">
          as of {formatDate(asOf)}
        </p>
      ) : null}
    </Card>
  );
}

export function SummaryCards({ data }: { data: DashboardResponse }) {
  const gain = data.total_gain;
  const tone = gainTone(gain);
  const sign = gain > 0 ? "+" : "";
  const Icon = gain < 0 ? TrendingDown : TrendingUp;

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Card size="sm" className="px-4">
        <Label>Total invested</Label>
        <p className="num text-lg font-semibold lg:text-xl">
          {formatINR(data.total_invested)}
        </p>
      </Card>
      <Card size="sm" className="px-4">
        <Label>Current value</Label>
        <p className="num text-lg font-semibold lg:text-xl">
          {formatINR(data.total_current)}
        </p>
      </Card>
      <Card size="sm" className="px-4">
        <Label>Gain / loss</Label>
        <div className="flex flex-wrap items-baseline gap-x-2">
          <p
            className={cn(
              "num text-lg font-semibold whitespace-nowrap lg:text-xl",
              tone,
            )}
          >
            {sign}
            {formatINR(gain)}
          </p>
          <p className={cn("num flex items-center gap-1 text-xs", tone)}>
            {gain !== 0 ? <Icon className="size-3" aria-hidden /> : null}
            {sign}
            {formatPct(data.gain_pct)}
          </p>
        </div>
      </Card>
      <DayChangeCard data={data} />
    </div>
  );
}

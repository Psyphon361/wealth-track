import { TrendingDown, TrendingUp } from "lucide-react";
import { formatINR, formatPct } from "@/lib/format";
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

function DayChange({ data }: { data: DashboardResponse }) {
  const change = data.day_change;
  const pct = data.day_change_pct;
  const tone = change === null ? "text-foreground" : gainTone(change);
  const sign = change !== null && change > 0 ? "+" : "";
  const Icon = change !== null && change < 0 ? TrendingDown : TrendingUp;

  return (
    <div className="min-w-0">
      <Label>1-day change</Label>
      <p className={cn("num text-base font-semibold whitespace-nowrap", tone)}>
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
        <p className={cn("num flex items-center gap-1 text-xs whitespace-nowrap", tone)}>
          {change !== 0 ? <Icon className="size-3" aria-hidden /> : null}
          {sign}
          {formatPct(pct)}
        </p>
      ) : null}
    </div>
  );
}

/** Invested, gain / loss and 1-day change, shown under the net worth figure. */
export function SummaryStats({ data }: { data: DashboardResponse }) {
  const gain = data.total_gain;
  const tone = gainTone(gain);
  const sign = gain > 0 ? "+" : "";
  const Icon = gain < 0 ? TrendingDown : TrendingUp;

  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
      <div className="min-w-0">
        <Label>Invested</Label>
        <p className="num text-base font-semibold whitespace-nowrap">
          {formatINR(data.total_invested)}
        </p>
      </div>
      <div className="min-w-0">
        <Label>Gain / loss</Label>
        <p className={cn("num text-base font-semibold whitespace-nowrap", tone)}>
          {sign}
          {formatINR(gain)}
        </p>
        <p className={cn("num flex items-center gap-1 text-xs whitespace-nowrap", tone)}>
          {gain !== 0 ? <Icon className="size-3" aria-hidden /> : null}
          {sign}
          {formatPct(data.gain_pct)}
        </p>
      </div>
      <DayChange data={data} />
    </div>
  );
}

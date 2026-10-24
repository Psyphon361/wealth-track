import { TrendingDown, TrendingUp } from "lucide-react";
import { Card } from "@/components/ui/card";
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

export function SummaryCards({ data }: { data: DashboardResponse }) {
  const gain = data.total_gain;
  const tone = gainTone(gain);
  const sign = gain > 0 ? "+" : "";
  const Icon = gain < 0 ? TrendingDown : TrendingUp;

  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <Card size="sm" className="px-4">
        <Label>Total invested</Label>
        <p className="num text-xl font-semibold">
          {formatINR(data.total_invested)}
        </p>
      </Card>
      <Card size="sm" className="px-4">
        <Label>Current value</Label>
        <p className="num text-xl font-semibold">
          {formatINR(data.total_current)}
        </p>
      </Card>
      <Card size="sm" className="px-4">
        <Label>Gain / loss</Label>
        <div className="flex flex-wrap items-baseline gap-x-2">
          <p className={cn("num text-xl font-semibold", tone)}>
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
    </div>
  );
}

import { TrendingDown, TrendingUp } from "lucide-react";
import { Card } from "@/components/ui/card";
import { gainTone } from "@/components/portfolio/grid/gain-cell";
import type { DetailKpi } from "@/components/portfolio/grid/types";
import { formatINR, formatPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { HoldingRow } from "@/lib/types";
import { LABEL } from "./sections";

function Kpi({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Card size="sm" className="min-w-0 gap-1 px-4">
      <p className={LABEL}>{label}</p>
      {children}
    </Card>
  );
}

export function KpiStrip({
  item,
  fourth,
}: {
  item: HoldingRow;
  fourth: DetailKpi;
}) {
  const tone = gainTone(item.gain);
  const sign = item.gain > 0 ? "+" : "";
  const Icon = item.gain < 0 ? TrendingDown : TrendingUp;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <Kpi label="Invested">
        <p className="num truncate text-lg font-semibold whitespace-nowrap lg:text-xl">
          {formatINR(item.invested)}
        </p>
      </Kpi>
      <Kpi label="Current value">
        <p className="num truncate text-lg font-semibold whitespace-nowrap lg:text-xl">
          {formatINR(item.current_value)}
        </p>
      </Kpi>
      <Kpi label="Gain">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <p
            className={cn(
              "num text-lg font-semibold whitespace-nowrap lg:text-xl",
              tone,
            )}
          >
            {sign}
            {formatINR(item.gain)}
          </p>
          <p className={cn("num flex items-center gap-1 text-xs", tone)}>
            {item.gain !== 0 ? <Icon className="size-3" aria-hidden /> : null}
            {sign}
            {formatPct(item.gain_pct)}
          </p>
        </div>
      </Kpi>
      <Kpi label={fourth.label}>
        <p className="truncate text-lg font-semibold whitespace-nowrap lg:text-xl">
          {fourth.value}
        </p>
        {fourth.sub ? (
          <p className="text-xs text-muted-foreground">{fourth.sub}</p>
        ) : null}
      </Kpi>
    </div>
  );
}

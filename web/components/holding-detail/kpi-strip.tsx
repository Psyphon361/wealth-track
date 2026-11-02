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
  showGain = true,
}: {
  item: HoldingRow;
  fourth: DetailKpi;
  showGain?: boolean;
}) {
  // "Other" holdings without an invested amount have no gain (the strip hides it).
  const gain = item.gain ?? 0;
  const gainPct = item.gain_pct ?? 0;
  const tone = gainTone(gain);
  const sign = gain > 0 ? "+" : "";
  const Icon = gain < 0 ? TrendingDown : TrendingUp;
  return (
    <div
      className={cn(
        "grid grid-cols-2 gap-3",
        showGain ? "sm:grid-cols-4" : "sm:grid-cols-3",
      )}
    >
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
      {showGain ? (
      <Kpi label="Gain">
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
            {formatPct(gainPct)}
          </p>
        </div>
      </Kpi>
      ) : null}
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

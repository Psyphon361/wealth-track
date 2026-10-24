import { TrendingDown, TrendingUp } from "lucide-react";
import { formatINR, formatPct } from "@/lib/format";
import { cn } from "@/lib/utils";

export function gainTone(gain: number): string {
  return gain > 0 ? "text-gain" : gain < 0 ? "text-loss" : "text-foreground";
}

export function GainCell({
  gain,
  pct,
  showPct = true,
}: {
  gain: number;
  pct: number;
  showPct?: boolean;
}) {
  const sign = gain > 0 ? "+" : "";
  return (
    <span
      className={cn(
        "num inline-flex items-baseline gap-1.5 whitespace-nowrap",
        gainTone(gain),
      )}
    >
      {sign}
      {formatINR(gain)}
      <span className="flex items-center gap-0.5 text-[11px] opacity-80">
        {gain > 0 ? (
          <TrendingUp className="size-3" aria-hidden />
        ) : gain < 0 ? (
          <TrendingDown className="size-3" aria-hidden />
        ) : null}
        {showPct ? (
          <>
            {sign}
            {formatPct(pct)}
          </>
        ) : null}
      </span>
    </span>
  );
}

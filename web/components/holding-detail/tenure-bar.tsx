import { Card } from "@/components/ui/card";
import { formatDate } from "@/lib/format";
import { elapsedPct } from "./utils";
import { LABEL } from "./sections";

export function TenureBar({ start, end }: { start: string; end: string }) {
  const pct = elapsedPct(start, end);
  return (
    <Card size="sm" className="gap-2 px-4">
      <div className="flex items-baseline justify-between">
        <p className={LABEL}>Tenure</p>
        <p className="num text-xs text-muted-foreground">
          {pct.toFixed(0)}% elapsed
        </p>
      </div>
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(pct)}
        className="h-1.5 overflow-hidden rounded-full bg-muted"
      >
        <div className="h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
      </div>
      <div className="num flex justify-between text-xs text-muted-foreground">
        <span>{formatDate(start)}</span>
        <span>{formatDate(end)}</span>
      </div>
    </Card>
  );
}

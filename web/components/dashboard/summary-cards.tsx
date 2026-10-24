import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatINR, formatPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { DashboardResponse } from "@/lib/types";

export function SummaryCards({ data }: { data: DashboardResponse }) {
  const gain = data.total_gain;
  const tone =
    gain > 0
      ? "text-green-600 dark:text-green-500"
      : gain < 0
        ? "text-red-600 dark:text-red-500"
        : "text-foreground";
  const sign = gain > 0 ? "+" : "";

  return (
    <div className="grid gap-4 sm:grid-cols-3">
      <Card>
        <CardHeader>
          <CardTitle className="text-muted-foreground">Total invested</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-semibold">
            {formatINR(data.total_invested)}
          </p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle className="text-muted-foreground">Current value</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-semibold">
            {formatINR(data.total_current)}
          </p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle className="text-muted-foreground">Gain / loss</CardTitle>
        </CardHeader>
        <CardContent>
          <p className={cn("text-2xl font-semibold", tone)}>
            {sign}
            {formatINR(gain)}
          </p>
          <p className={cn("text-sm", tone)}>
            {sign}
            {formatPct(data.gain_pct)}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

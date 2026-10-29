import Link from "next/link";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatINR, formatPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ASSET_TYPE_LABELS, type DashboardResponse } from "@/lib/types";

const head = "h-9 text-[12px] font-medium tracking-wider text-muted-foreground uppercase";

export function HoldingsByType({ data }: { data: DashboardResponse }) {
  const totalCount = data.by_type.reduce((s, r) => s + r.count, 0);
  const totalAllocation = data.by_type.reduce((s, r) => s + r.allocation_pct, 0);

  return (
    <Card size="sm" className="gap-0 py-0">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className={cn(head, "pl-4")}>Asset type</TableHead>
            <TableHead className={cn(head, "text-right")}>Count</TableHead>
            <TableHead className={cn(head, "text-right")}>Invested</TableHead>
            <TableHead className={cn(head, "text-right")}>Current value</TableHead>
            <TableHead className={cn(head, "pr-4 text-right")}>Allocation</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.by_type.map((r) => (
            <TableRow
              key={r.type}
              className={cn(
                "h-9 border-border/40 hover:bg-muted/30",
                r.count === 0 && "text-muted-foreground/60",
              )}
            >
              <TableCell className="py-1.5 pl-4">
                <Link
                  href={`/portfolio/${r.type}`}
                  className="rounded-sm font-medium underline-offset-4 outline-none hover:text-primary hover:underline focus-visible:ring-2 focus-visible:ring-ring/50"
                >
                  {ASSET_TYPE_LABELS[r.type] ?? r.label}
                </Link>
              </TableCell>
              <TableCell className="num py-1.5 text-right">
                {r.count}
                {r.matured_count > 0 ? (
                  <span className="ml-1 text-[11px] text-muted-foreground">
                    +{r.matured_count} matured
                  </span>
                ) : null}
              </TableCell>
              <TableCell className="num py-1.5 text-right">
                {formatINR(r.invested)}
              </TableCell>
              <TableCell className="num py-1.5 text-right">
                {formatINR(r.current)}
              </TableCell>
              <TableCell className="py-1.5 pr-4">
                <div className="flex items-center justify-end gap-2">
                  <div className="hidden h-1 w-16 overflow-hidden rounded-full bg-muted sm:block">
                    <div
                      className="h-full rounded-full bg-foreground/50"
                      style={{
                        width: `${Math.min(100, Math.max(0, r.allocation_pct))}%`,
                      }}
                    />
                  </div>
                  <span className="num w-14 text-right">
                    {formatPct(r.allocation_pct)}
                  </span>
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
        <TableFooter className="border-t border-border/60 bg-transparent">
          <TableRow className="h-9 hover:bg-transparent">
            <TableCell className="py-1.5 pl-4 font-medium">Total</TableCell>
            <TableCell className="num py-1.5 text-right font-medium">
              {totalCount}
            </TableCell>
            <TableCell className="num py-1.5 text-right font-medium">
              {formatINR(data.total_invested)}
            </TableCell>
            <TableCell className="num py-1.5 text-right font-medium">
              {formatINR(data.total_current)}
            </TableCell>
            <TableCell className="num py-1.5 pr-4 text-right font-medium">
              {formatPct(totalAllocation)}
            </TableCell>
          </TableRow>
        </TableFooter>
      </Table>
    </Card>
  );
}

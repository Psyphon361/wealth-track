import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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

export function HoldingsByType({ data }: { data: DashboardResponse }) {
  const totalCount = data.by_type.reduce((s, r) => s + r.count, 0);
  const totalAllocation = data.by_type.reduce((s, r) => s + r.allocation_pct, 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Holdings by type</CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Asset type</TableHead>
              <TableHead className="text-right">Count</TableHead>
              <TableHead className="text-right">Invested</TableHead>
              <TableHead className="text-right">Current value</TableHead>
              <TableHead className="text-right">Allocation</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.by_type.map((r) => (
              <TableRow
                key={r.type}
                className={cn(r.count === 0 && "text-muted-foreground")}
              >
                <TableCell>
                  <Link
                    href="/portfolio"
                    className="font-medium underline-offset-4 hover:underline"
                  >
                    {ASSET_TYPE_LABELS[r.type] ?? r.label}
                  </Link>
                </TableCell>
                <TableCell className="text-right">{r.count}</TableCell>
                <TableCell className="text-right">{formatINR(r.invested)}</TableCell>
                <TableCell className="text-right">{formatINR(r.current)}</TableCell>
                <TableCell className="text-right">
                  {formatPct(r.allocation_pct)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
          <TableFooter>
            <TableRow>
              <TableCell className="font-semibold">Total</TableCell>
              <TableCell className="text-right font-semibold">{totalCount}</TableCell>
              <TableCell className="text-right font-semibold">
                {formatINR(data.total_invested)}
              </TableCell>
              <TableCell className="text-right font-semibold">
                {formatINR(data.total_current)}
              </TableCell>
              <TableCell className="text-right font-semibold">
                {formatPct(totalAllocation)}
              </TableCell>
            </TableRow>
          </TableFooter>
        </Table>
      </CardContent>
    </Card>
  );
}

import { Fragment } from "react";
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
import { getAssetEntry } from "@/lib/asset-catalog";
import { assetColor } from "@/lib/asset-colors";
import { groupRows } from "@/lib/dashboard-groups";
import { formatINR, formatPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ASSET_TYPE_LABELS, type DashboardResponse } from "@/lib/types";

const head = "h-9 text-[11px] font-medium tracking-wider text-muted-foreground uppercase";
const narrow = "hidden sm:table-cell";

function tone(n: number | null): string {
  if (n === null || n === 0) return "";
  return n > 0 ? "text-gain" : "text-loss";
}

function signed(n: number): string {
  return n > 0 ? `+${formatINR(n)}` : formatINR(n);
}

function signedPct(n: number): string {
  return n > 0 ? `+${formatPct(n)}` : formatPct(n);
}

function Gain({
  value,
  pct,
  bold,
}: {
  value: number | null;
  pct: number | null;
  bold?: boolean;
}) {
  if (value === null) return <span className="text-muted-foreground">—</span>;
  return (
    <span className={cn("inline-flex flex-col items-end", tone(value))}>
      <span className={cn("whitespace-nowrap", bold && "font-medium")}>{signed(value)}</span>
      {pct !== null && <span className="text-xs whitespace-nowrap">{signedPct(pct)}</span>}
    </span>
  );
}

export function HoldingsByType({ data }: { data: DashboardResponse }) {
  const totalCount = data.by_type.reduce((s, r) => s + r.count, 0);
  // Per-type percentages are rounded, so their sum can drift from 100.
  const totalAllocation =
    data.total_current > 0
      ? 100
      : data.by_type.reduce((s, r) => s + r.allocation_pct, 0);
  const groups = groupRows(data.by_type);

  return (
    <Card size="sm" className="gap-0 py-0">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className={cn(head, "pl-4")}>Asset type</TableHead>
            <TableHead className={cn(head, "text-right", narrow)}>Count</TableHead>
            <TableHead className={cn(head, "text-right", narrow)}>Invested</TableHead>
            <TableHead className={cn(head, "text-right")}>Current value</TableHead>
            <TableHead className={cn(head, "text-right")}>Gain</TableHead>
            <TableHead className={cn(head, "text-right", narrow)}>1-day</TableHead>
            <TableHead className={cn(head, "pr-4 text-right")}>Allocation</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {groups.map((g) => (
            <Fragment key={g.name}>
              {g.showSubtotal && (
                <TableRow className="h-9 border-border/40 bg-muted/20 hover:bg-muted/20">
                  <TableCell className="py-1.5 pl-4 text-[11px] font-medium tracking-wider text-muted-foreground uppercase">
                    {g.name}
                  </TableCell>
                  <TableCell className={cn("num py-1.5 text-right text-[13.5px] font-medium", narrow)}>
                    {g.subtotal.count}
                  </TableCell>
                  <TableCell
                    className={cn("num py-1.5 text-right text-[13.5px] font-medium whitespace-nowrap", narrow)}
                  >
                    {formatINR(g.subtotal.invested)}
                  </TableCell>
                  <TableCell className="num py-1.5 text-right text-[13.5px] font-medium whitespace-nowrap">
                    {formatINR(g.subtotal.current)}
                  </TableCell>
                  <TableCell className="num py-1.5 text-right text-[13.5px] whitespace-nowrap">
                    <Gain value={g.subtotal.gain} pct={g.subtotal.gain_pct} bold />
                  </TableCell>
                  <TableCell
                    className={cn("num py-1.5 text-right text-[13.5px] whitespace-nowrap", narrow)}
                  >
                    <Gain value={g.subtotal.day_change} pct={null} bold />
                  </TableCell>
                  <TableCell className="num py-1.5 pr-4 text-right text-[13.5px] font-medium whitespace-nowrap">
                    {formatPct(g.subtotal.allocation_pct)}
                  </TableCell>
                </TableRow>
              )}
              {g.rows.map((r) => {
                const entry = getAssetEntry(r.type);
                const Icon = entry?.icon;
                return (
                  <TableRow
                    key={r.type}
                    className="relative h-9 cursor-pointer border-border/40 hover:bg-muted/30 focus-within:ring-2 focus-within:ring-ring/50 focus-within:ring-inset"
                  >
                    <TableCell className="py-1.5 pl-4">
                      <span className="flex items-center gap-2">
                        {Icon && (
                          <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                            <Icon className="size-3.5" />
                          </span>
                        )}
                        <Link
                          href={`/portfolio/${r.type}`}
                          className="font-medium outline-none after:absolute after:inset-0 after:content-['']"
                        >
                          {ASSET_TYPE_LABELS[r.type] ?? r.label}
                        </Link>
                      </span>
                    </TableCell>
                    <TableCell className={cn("num py-1.5 text-right", narrow)}>
                      {r.count}
                    </TableCell>
                    <TableCell className={cn("num py-1.5 text-right whitespace-nowrap", narrow)}>
                      {formatINR(r.invested)}
                    </TableCell>
                    <TableCell className="num py-1.5 text-right whitespace-nowrap">
                      {formatINR(r.current)}
                    </TableCell>
                    <TableCell className="num py-1.5 text-right whitespace-nowrap">
                      <Gain value={r.gain} pct={r.gain_pct} />
                    </TableCell>
                    <TableCell className={cn("num py-1.5 text-right whitespace-nowrap", narrow)}>
                      <Gain value={r.day_change} pct={null} />
                    </TableCell>
                    <TableCell className="py-1.5 pr-4">
                      <div className="flex items-center justify-end gap-2">
                        <div className="hidden h-1 w-16 overflow-hidden rounded-full bg-muted sm:block">
                          <div
                            className="h-full rounded-full"
                            style={{
                              width: `${Math.min(100, Math.max(0, r.allocation_pct))}%`,
                              backgroundColor: assetColor(r.type),
                            }}
                          />
                        </div>
                        <span className="num w-14 text-right whitespace-nowrap">
                          {formatPct(r.allocation_pct)}
                        </span>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </Fragment>
          ))}
        </TableBody>
        <TableFooter className="border-t-2 border-foreground/20 bg-muted/30 font-semibold">
          <TableRow className="h-10 hover:bg-transparent">
            <TableCell className="py-1.5 pl-4 text-[13.5px] font-semibold">Total</TableCell>
            <TableCell className={cn("num py-1.5 text-right text-[13.5px] font-semibold", narrow)}>
              {totalCount}
            </TableCell>
            <TableCell
              className={cn("num py-1.5 text-right text-[13.5px] font-semibold whitespace-nowrap", narrow)}
            >
              {formatINR(data.total_invested)}
            </TableCell>
            <TableCell className="num py-1.5 text-right text-[13.5px] font-semibold whitespace-nowrap">
              {formatINR(data.total_current)}
            </TableCell>
            <TableCell className="num py-1.5 text-right text-[13.5px] font-semibold whitespace-nowrap">
              <Gain value={data.total_gain} pct={data.gain_pct} bold />
            </TableCell>
            <TableCell
              className={cn("num py-1.5 text-right text-[13.5px] font-semibold whitespace-nowrap", narrow)}
            >
              <Gain value={data.day_change} pct={data.day_change_pct} bold />
            </TableCell>
            <TableCell className="num py-1.5 pr-4 text-right text-[13.5px] font-semibold whitespace-nowrap">
              {formatPct(totalAllocation)}
            </TableCell>
          </TableRow>
        </TableFooter>
      </Table>
    </Card>
  );
}

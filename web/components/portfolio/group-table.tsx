"use client";

import Link from "next/link";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatINR } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  ASSET_TYPE_LABELS,
  type AssetType,
  type ComputedFields,
  type PortfolioGroup,
} from "@/lib/types";
import { GainCell, type Column } from "./columns";

interface Props<T extends ComputedFields & { id: number }> {
  group: PortfolioGroup;
  items: T[];
  columns: Column<T>[];
  onEdit: (item: T) => void;
  onDelete: (item: T) => void;
}

export function GroupTable<T extends ComputedFields & { id: number }>({
  group,
  items,
  columns,
  onEdit,
  onDelete,
}: Props<T>) {
  const type: AssetType = group.type;
  const investedIdx = columns.findIndex((c) => c.header === "Invested");
  const trailing = columns.length - investedIdx - 3;
  const { totals } = group;

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">
          {ASSET_TYPE_LABELS[type] ?? group.label}{" "}
          <span className="text-sm font-normal text-muted-foreground">
            ({items.length})
          </span>
        </h2>
        <Link
          href={`/add?type=${type}`}
          className={buttonVariants({ variant: "outline", size: "sm" })}
        >
          Add
        </Link>
      </div>
      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              {columns.map((c) => (
                <TableHead
                  key={c.header}
                  className={cn(c.align === "right" && "text-right")}
                >
                  {c.header}
                </TableHead>
              ))}
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => (
              <TableRow key={item.id}>
                {columns.map((c) => (
                  <TableCell
                    key={c.header}
                    className={cn(c.align === "right" && "text-right")}
                  >
                    {c.cell(item)}
                  </TableCell>
                ))}
                <TableCell className="text-right">
                  <div className="flex justify-end gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => onEdit(item)}
                    >
                      Edit
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-destructive"
                      onClick={() => onDelete(item)}
                    >
                      Delete
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
          <TableFooter>
            <TableRow>
              <TableCell colSpan={investedIdx} className="font-semibold">
                Total
              </TableCell>
              <TableCell className="text-right font-semibold whitespace-nowrap">
                {formatINR(totals.invested)}
              </TableCell>
              <TableCell className="text-right font-semibold whitespace-nowrap">
                {formatINR(totals.current_value)}
              </TableCell>
              <TableCell className="text-right font-semibold">
                <GainCell gain={totals.gain} pct={totals.gain_pct} />
              </TableCell>
              <TableCell colSpan={trailing + 1} />
            </TableRow>
          </TableFooter>
        </Table>
      </div>
    </section>
  );
}

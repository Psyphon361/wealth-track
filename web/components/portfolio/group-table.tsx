"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
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
  updatingIds?: ReadonlySet<number>;
}

const head =
  "h-9 text-[11px] font-medium tracking-wider whitespace-nowrap text-muted-foreground uppercase";

function IconAction({
  label,
  onClick,
  className,
  children,
}: {
  label: string;
  onClick: () => void;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            aria-label={label}
            className={cn("text-muted-foreground", className)}
            onClick={onClick}
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

export function GroupTable<T extends ComputedFields & { id: number }>({
  group,
  items,
  columns,
  onEdit,
  onDelete,
  updatingIds,
}: Props<T>) {
  const type: AssetType = group.type;
  const investedIdx = columns.findIndex((c) => c.header === "Invested");
  const trailing = columns.length - investedIdx - 3;
  const { totals } = group;

  return (
    <Card size="sm" className="gap-0 py-0">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-medium">
            {ASSET_TYPE_LABELS[type] ?? group.label}
          </h2>
          <Badge variant="secondary" className="num h-4 px-1.5 text-[10px]">
            {items.length}
          </Badge>
        </div>
        <div className="flex items-center gap-3">
          <div className="num flex items-center gap-2 text-xs text-muted-foreground">
            <span>{formatINR(totals.current_value)}</span>
            <GainCell gain={totals.gain} pct={totals.gain_pct} />
          </div>
          <Link
            href={`/add/${type}`}
            className={buttonVariants({ variant: "ghost", size: "xs" })}
          >
            <Plus data-icon="inline-start" />
            Add
          </Link>
        </div>
      </div>
      <TooltipProvider>
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              {columns.map((c, i) => (
                <TableHead
                  key={c.header}
                  className={cn(
                    head,
                    i === 0 && "pl-4",
                    c.align === "right" && "text-right",
                  )}
                >
                  {c.header}
                </TableHead>
              ))}
              <TableHead className={cn(head, "w-20 pr-4")}>
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => (
              <TableRow
                key={item.id}
                aria-busy={updatingIds?.has(item.id) || undefined}
                className={cn(
                  "h-9 border-border/40 transition-opacity hover:bg-muted/30",
                  updatingIds?.has(item.id) && "animate-pulse opacity-50",
                )}
              >
                {columns.map((c, i) => (
                  <TableCell
                    key={c.header}
                    className={cn(
                      "py-1.5",
                      i === 0 && "pl-4",
                      c.align === "right" && "text-right",
                    )}
                  >
                    {c.cell(item)}
                  </TableCell>
                ))}
                <TableCell className="py-1.5 pr-4">
                  <div className="flex justify-end gap-0.5">
                    <IconAction label="Edit" onClick={() => onEdit(item)}>
                      <Pencil />
                    </IconAction>
                    <IconAction
                      label="Delete"
                      className="hover:text-destructive"
                      onClick={() => onDelete(item)}
                    >
                      <Trash2 />
                    </IconAction>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
          <TableFooter className="border-t border-border/60 bg-transparent">
            <TableRow className="h-9 hover:bg-transparent">
              <TableCell
                colSpan={investedIdx}
                className="py-1.5 pl-4 text-xs font-medium text-muted-foreground"
              >
                Total
              </TableCell>
              <TableCell className="num py-1.5 text-right font-medium whitespace-nowrap">
                {formatINR(totals.invested)}
              </TableCell>
              <TableCell className="num py-1.5 text-right font-medium whitespace-nowrap">
                {formatINR(totals.current_value)}
              </TableCell>
              <TableCell className="py-1.5 text-right font-medium">
                <GainCell gain={totals.gain} pct={totals.gain_pct} />
              </TableCell>
              <TableCell colSpan={trailing + 1} />
            </TableRow>
          </TableFooter>
        </Table>
      </TooltipProvider>
    </Card>
  );
}

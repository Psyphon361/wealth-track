"use client";

import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";
import type { Column, RowData, Table } from "@tanstack/react-table";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { DEFAULT_DIR, DEFAULT_SORT } from "./use-holdings-query";
import type { gridFeatures } from "./features";

type Features = typeof gridFeatures;

export function sortAria(
  dir: false | "asc" | "desc",
): "ascending" | "descending" | "none" {
  return dir === "asc" ? "ascending" : dir === "desc" ? "descending" : "none";
}

/**
 * Sortable header button. Click cycles desc -> asc -> default sort.
 */
export function ColumnHeader<TRow extends RowData, TValue>({
  column,
  table,
  title,
}: {
  column: Column<Features, TRow, TValue>;
  table: Table<Features, TRow>;
  title: string;
}) {
  const dir = column.getIsSorted();

  function cycle() {
    if (dir === false) {
      table.setSorting([{ id: column.id, desc: true }]);
    } else if (dir === "desc") {
      table.setSorting([{ id: column.id, desc: false }]);
    } else {
      table.setSorting([{ id: DEFAULT_SORT, desc: DEFAULT_DIR === "desc" }]);
    }
  }

  const Icon = dir === "asc" ? ArrowUp : dir === "desc" ? ArrowDown : ChevronsUpDown;

  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      onClick={cycle}
      className={cn(
        "-mx-2 h-7 gap-1 px-2 text-[11px] font-medium tracking-wider text-muted-foreground uppercase hover:text-foreground",
        dir !== false && "text-foreground",
      )}
    >
      {title}
      <Icon
        aria-hidden
        className={cn("size-3", dir === false && "opacity-50")}
      />
    </Button>
  );
}

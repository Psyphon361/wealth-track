"use client";

import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
} from "lucide-react";
import type { ReactTable, RowData } from "@tanstack/react-table";
import { Button } from "@/components/ui/button";
import type { gridFeatures } from "./features";

export function Pagination<TRow extends RowData>({
  table,
}: {
  table: ReactTable<typeof gridFeatures, TRow>;
}) {
  const { pageIndex } = table.state.pagination;
  const pageCount = Math.max(1, table.getPageCount());
  const atStart = pageIndex <= 0;
  const atEnd = pageIndex + 1 >= pageCount;

  return (
    <div className="flex flex-wrap items-center justify-end gap-x-6 gap-y-2">
      <div className="flex items-center gap-2">
        <span className="num text-xs text-muted-foreground">
          Page {Math.min(pageIndex + 1, pageCount)} of {pageCount}
        </span>
        <div className="flex items-center gap-1">
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            aria-label="First page"
            disabled={atStart}
            onClick={() => table.setPageIndex(0)}
          >
            <ChevronsLeft />
          </Button>
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            aria-label="Previous page"
            disabled={atStart}
            onClick={() => table.setPageIndex(pageIndex - 1)}
          >
            <ChevronLeft />
          </Button>
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            aria-label="Next page"
            disabled={atEnd}
            onClick={() => table.setPageIndex(pageIndex + 1)}
          >
            <ChevronRight />
          </Button>
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            aria-label="Last page"
            disabled={atEnd}
            onClick={() => table.setPageIndex(pageCount - 1)}
          >
            <ChevronsRight />
          </Button>
        </div>
      </div>
    </div>
  );
}

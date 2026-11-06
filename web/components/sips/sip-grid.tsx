"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Plus, X } from "lucide-react";
import {
  functionalUpdate,
  useTable,
  type PaginationState,
  type SortingState,
} from "@tanstack/react-table";
import { TableSkeleton } from "@/components/portfolio/grid/data-table";
import {
  FacetedFilter,
  type FacetOption,
} from "@/components/portfolio/grid/faceted-filter";
import { gridFeatures } from "@/components/portfolio/grid/features";
import { sortAria } from "@/components/portfolio/grid/column-header";
import { Pagination } from "@/components/portfolio/grid/pagination";
import { SearchInput } from "@/components/portfolio/grid/toolbar";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { todayISO } from "@/components/forms/schema";
import { formatINRWhole } from "@/lib/format";
import {
  ADD_SIP_HREF,
  DEFAULT_SIP_SORT,
  SIP_SORT_KEYS,
  STATUS_LABELS,
  filterSips,
  sipSummary,
  sortSips,
  summaryLine,
  type SipSortKey,
} from "@/lib/sip";
import type { Sip, SipStatus } from "@/lib/types";
import { createSipColumns } from "./sip-grid-config";
import { useSips } from "./use-sips";

const LABEL =
  "text-[11px] font-medium tracking-wider text-muted-foreground uppercase";

const PAGE_SIZE = 10;

const STATUSES: SipStatus[] = ["active", "paused", "stopped"];

function isSortKey(id: string): id is SipSortKey {
  return (SIP_SORT_KEYS as readonly string[]).includes(id);
}

/** One compact row, like the holdings summary strip, plus the Start a SIP button. */
function SipSummaryStrip({ sips }: { sips: Sip[] }) {
  const summary = sipSummary(sips);
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <dl className="flex flex-wrap items-baseline gap-x-5 gap-y-1 text-[13.5px]">
        <div className="flex items-baseline gap-1.5">
          <dt className={LABEL}>Monthly SIPs</dt>
          <dd className="num font-medium">{formatINRWhole(summary.monthly)}</dd>
        </div>
        <div className="num text-muted-foreground">{summaryLine(summary)}</div>
        <div className="flex items-baseline gap-1.5">
          <dt className={LABEL}>Invested via SIPs</dt>
          <dd className="num">{formatINRWhole(summary.invested)}</dd>
        </div>
        <div className="flex items-baseline gap-1.5">
          <dt className={LABEL}>Instalments added</dt>
          <dd className="num">{summary.instalments}</dd>
        </div>
      </dl>
      <Link
        href={ADD_SIP_HREF}
        className={buttonVariants({ variant: "outline", size: "sm" })}
      >
        <Plus aria-hidden />
        Start a SIP
      </Link>
    </div>
  );
}

function SipTable({
  sips,
  today,
  onChanged,
}: {
  sips: Sip[];
  today: string;
  onChanged: () => void;
}) {
  const [q, setQ] = useState("");
  const [statuses, setStatuses] = useState<SipStatus[]>([]);
  const [sort, setSort] = useState<{ id: SipSortKey; desc: boolean }>({
    id: DEFAULT_SIP_SORT,
    desc: false,
  });
  const [page, setPage] = useState(1);

  const columns = useMemo(
    () => createSipColumns({ today, onChanged }),
    [today, onChanged],
  );

  const filtered = useMemo(
    () => filterSips(sips, q, statuses),
    [sips, q, statuses],
  );
  const sorted = useMemo(
    () => sortSips(filtered, sort.id, sort.desc),
    [filtered, sort],
  );
  const pageCount = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const pageIndex = Math.min(page, pageCount) - 1;
  const items = useMemo(
    () => sorted.slice(pageIndex * PAGE_SIZE, (pageIndex + 1) * PAGE_SIZE),
    [sorted, pageIndex],
  );

  const sorting = useMemo<SortingState>(
    () => [{ id: sort.id, desc: sort.desc }],
    [sort],
  );
  const pagination = useMemo<PaginationState>(
    () => ({ pageIndex, pageSize: PAGE_SIZE }),
    [pageIndex],
  );
  const state = useMemo(() => ({ sorting, pagination }), [sorting, pagination]);

  const table = useTable({
    features: gridFeatures,
    columns,
    data: items,
    getRowId: (row) => String(row.id),
    manualSorting: true,
    manualFiltering: true,
    manualPagination: true,
    rowCount: sorted.length,
    state,
    onSortingChange: (updater) => {
      const next = functionalUpdate(updater, sorting)[0];
      setSort(
        next && isSortKey(next.id)
          ? { id: next.id, desc: next.desc }
          : { id: DEFAULT_SIP_SORT, desc: false },
      );
      setPage(1);
    },
    onPaginationChange: (updater) => {
      setPage(functionalUpdate(updater, pagination).pageIndex + 1);
    },
  });

  const counts = useMemo(() => {
    const map = new Map<SipStatus, number>();
    for (const s of sips) map.set(s.status, (map.get(s.status) ?? 0) + 1);
    return map;
  }, [sips]);
  const statusOptions: FacetOption<SipStatus>[] = STATUSES.filter(
    (s) => counts.has(s) || statuses.includes(s),
  ).map((s) => ({
    value: s,
    label: STATUS_LABELS[s],
    count: counts.get(s) ?? 0,
  }));

  const hasFilters = q.trim() !== "" || statuses.length > 0;
  function reset() {
    setQ("");
    setStatuses([]);
    setPage(1);
  }

  const rows = table.getRowModel().rows;
  const visibleCount = table.getVisibleLeafColumns().length;

  return (
    <div className="min-w-0 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <SearchInput
          value={q}
          placeholder="Search SIPs…"
          label="Search SIPs"
          onSearch={(next) => {
            setQ(next);
            setPage(1);
          }}
        />
        <FacetedFilter
          title="Status"
          options={statusOptions}
          selected={statuses}
          onChange={(next) => {
            setStatuses(next);
            setPage(1);
          }}
        />
        {hasFilters ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-8 text-[12.5px]"
            onClick={reset}
          >
            <X aria-hidden />
            Reset
          </Button>
        ) : null}
      </div>

      <div className="relative min-w-0 overflow-hidden rounded-xl border">
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((group) => (
              <TableRow key={group.id} className="hover:bg-transparent">
                {group.headers.map((header) => (
                  <TableHead
                    key={header.id}
                    aria-sort={
                      header.column.getCanSort()
                        ? sortAria(header.column.getIsSorted())
                        : undefined
                    }
                    className="h-9 text-[11px] tracking-wider text-muted-foreground uppercase"
                  >
                    {header.isPlaceholder ? null : (
                      <table.FlexRender header={header} />
                    )}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow className="hover:bg-transparent">
                <TableCell
                  colSpan={visibleCount}
                  className="py-12 text-center text-muted-foreground"
                >
                  <p>No SIPs match your filters.</p>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="mt-3"
                    onClick={reset}
                  >
                    Reset
                  </Button>
                </TableCell>
              </TableRow>
            ) : (
              rows.map((row) => (
                <TableRow key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>
                      <table.FlexRender cell={cell} />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <Pagination table={table} />
    </div>
  );
}

/** The SIPs view on /portfolio/mf: compact summary, then the SIPs in the standard holdings grid. */
export function SipGrid() {
  const { sips, error, reload, retry } = useSips();
  const [today] = useState(todayISO);

  if (error && !sips) {
    return (
      <div className="flex flex-col items-start gap-3 rounded-lg border border-destructive/30 p-4">
        <div>
          <p className="text-[13.5px] font-medium text-destructive">
            {error.message}
          </p>
          {error.description ? (
            <p className="text-[13.5px] text-muted-foreground">
              {error.description}
            </p>
          ) : null}
        </div>
        <Button variant="outline" onClick={retry}>
          Retry
        </Button>
      </div>
    );
  }

  if (!sips) return <TableSkeleton />;

  if (sips.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed py-16 text-center">
        <div className="space-y-1">
          <p className="text-sm font-medium">No SIPs yet</p>
          <p className="text-[13.2px] text-muted-foreground">
            Start one and its monthly instalments are added to your fund
            automatically.
          </p>
        </div>
        <Link href={ADD_SIP_HREF} className={buttonVariants({ size: "sm" })}>
          <Plus aria-hidden />
          Start a SIP
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <SipSummaryStrip sips={sips} />
      <SipTable sips={sips} today={today} onChanged={reload} />
    </div>
  );
}

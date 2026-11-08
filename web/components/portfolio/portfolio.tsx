"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Plus } from "lucide-react";
import { notify } from "@/lib/notify";
import { SipGrid } from "@/components/sips/sip-grid";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { apiDelete } from "@/lib/api";
import { invalidateNetWorth } from "@/lib/networth-cache";
import { markHoldingsStale } from "@/lib/holdings-cache";
import { formatINR, formatIstDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { AssetType, HoldingRow, HoldingsSummary } from "@/lib/types";
import { addLabel as addLabelFor, refreshAssetTabCounts } from "./asset-tabs";
import { DeleteDialog, type DeleteTarget } from "./delete-dialog";
import { EditDialog } from "./edit-dialog";
import { bondConfig } from "./grid/configs/bond";
import { cashConfig } from "./grid/configs/cash";
import { otherConfig } from "./grid/configs/other";
import { fdConfig } from "./grid/configs/fd";
import { goldConfig } from "./grid/configs/gold";
import { mfConfig } from "./grid/configs/mf";
import { npsConfig } from "./grid/configs/nps";
import { pfConfig } from "./grid/configs/pf";
import { rdConfig } from "./grid/configs/rd";
import { stockConfig } from "./grid/configs/stock";
import { HoldingsGrid, TableSkeleton } from "./grid/data-table";
import { GainCell } from "./grid/gain-cell";
import type { GridConfig } from "./grid/types";
import { hasActiveFilters, useHoldingsQuery } from "./grid/use-holdings-query";

const LABEL = "text-[11px] font-medium tracking-wider text-muted-foreground uppercase";

function StatusTabs({
  summary,
  closed,
  onChange,
}: {
  summary: HoldingsSummary;
  closed: boolean;
  onChange: (closed: boolean) => void;
}) {
  const tabs = [
    { value: false, label: "Active", n: summary.count },
    { value: true, label: "Closed", n: summary.closed_count },
  ];
  return (
    <div
      role="tablist"
      aria-label="Holding status"
      className="inline-flex items-center gap-0.5 rounded-md bg-muted p-0.5"
    >
      {tabs.map((t) => (
        <button
          key={t.label}
          type="button"
          role="tab"
          aria-selected={closed === t.value}
          onClick={() => closed !== t.value && onChange(t.value)}
          className={cn(
            "rounded-sm px-3 py-1.5 text-xs outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring/50",
            closed === t.value
              ? "bg-background font-medium text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {t.label} <span className="num">({t.n})</span>
        </button>
      ))}
    </div>
  );
}

function TotalsSkeleton() {
  return (
    <>
      {["Invested", "Current", "Gain"].map((label) => (
        <div key={label} className="flex items-baseline gap-1.5">
          <dt className={LABEL}>{label}</dt>
          <dd aria-busy="true" aria-label="Loading…">
            <Skeleton className="h-4 w-20" />
          </dd>
        </div>
      ))}
    </>
  );
}

function SummaryStrip({
  summary,
  showTotals = true,
  loadingTotals = false,
  tabs,
}: {
  summary: HoldingsSummary;
  showTotals?: boolean;
  /** Figures belong to the other status tab: show placeholders. */
  loadingTotals?: boolean;
  tabs?: ReactNode;
}) {
  return (
    <dl className="flex flex-wrap items-baseline gap-x-5 gap-y-1 text-[13.5px]">
      {tabs ?? (
        <div className="num font-medium">
          {summary.count} active
          {summary.closed_count > 0 ? (
            <span className="font-normal text-muted-foreground">
              {" "}
              · {summary.closed_count} closed
            </span>
          ) : null}
        </div>
      )}
      {showTotals ? (
        loadingTotals ? <TotalsSkeleton /> : <Totals summary={summary} />
      ) : null}
    </dl>
  );
}

function Totals({ summary }: { summary: HoldingsSummary }) {
  return (
    <>
      <div className="flex items-baseline gap-1.5">
        <dt className={LABEL}>Invested</dt>
        <dd className="num">{formatINR(summary.invested)}</dd>
      </div>
      <div className="flex items-baseline gap-1.5">
        <dt className={LABEL}>Current</dt>
        <dd className="num">{formatINR(summary.current_value)}</dd>
      </div>
      <div className="flex items-baseline gap-1.5">
        <dt className={LABEL}>Gain</dt>
        <dd>
          <GainCell gain={summary.gain} pct={summary.gain_pct} />
        </dd>
      </div>
    </>
  );
}

function TypedPortfolio<TRow extends HoldingRow>({
  config,
}: {
  config: GridConfig<TRow>;
}) {
  const q = useHoldingsQuery(config);
  const { refetch, removeItem } = q;
  const [editing, setEditing] = useState<TRow | null>(null);
  const [deleting, setDeleting] = useState<DeleteTarget | null>(null);
  const addLabel = addLabelFor(config.type);
  const count = q.data
    ? q.data.summary.count + q.data.summary.closed_count
    : undefined;

  useEffect(() => {
    if (count !== undefined) refreshAssetTabCounts();
  }, [count]);

  const onEdit = useCallback((row: TRow) => setEditing(row), []);
  const onDelete = useCallback(
    (row: TRow) =>
      setDeleting({ type: config.type, id: row.id, name: config.rowName(row) }),
    [config],
  );

  function handleSaved() {
    setEditing(null);
    refetch();
  }

  function handleDelete(target: DeleteTarget) {
    setDeleting(null);
    const restore = removeItem(target.id);
    apiDelete(`/assets/${target.type}/${target.id}`)
      .then((res) => {
        invalidateNetWorth();
        // Marking stale makes the grid's subscriber refetch (once).
        markHoldingsStale(target.type);
        notify.success(res);
      })
      .catch((err: unknown) => {
        restore();
        notify.error(err);
        refetch();
      });
  }

  if (q.status === "loading") {
    return <TableSkeleton />;
  }

  if (q.status === "error" || !q.data) {
    return (
      <>
        <div className="flex flex-col items-start gap-3 rounded-lg border border-destructive/30 p-4">
          <div>
            <p className="text-[13.5px] font-medium text-destructive">
              {q.error?.message}
            </p>
            {q.error?.description ? (
              <p className="text-[13.5px] text-muted-foreground">
                {q.error.description}
              </p>
            ) : null}
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={q.retry}>
              Retry
            </Button>
            {hasActiveFilters(q.filters) ? (
              <Button variant="ghost" onClick={q.resetFilters}>
                Reset
              </Button>
            ) : null}
          </div>
        </div>
      </>
    );
  }

  const { data, filters } = q;

  const noneYet = data.summary.count + data.summary.closed_count === 0;

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        {config.statusTabs ? (
          <SummaryStrip
            summary={data.summary}
            showTotals={!filters.closed}
            loadingTotals={q.switching}
            tabs={
              <StatusTabs
                summary={data.summary}
                closed={filters.closed}
                onChange={q.setClosed}
              />
            }
          />
        ) : (
          <SummaryStrip summary={data.summary} />
        )}
        <Link
          href={`/add/${config.type}`}
          className={buttonVariants({ variant: "outline", size: "sm" })}
        >
          <Plus aria-hidden />
          {addLabel}
        </Link>
      </div>

      {config.type === "stock" ? (
        <p className="text-xs text-muted-foreground">
          Prices are the NSE/BSE closing price, updated nightly.
          {data.prices_as_of
            ? ` Last updated ${formatIstDateTime(data.prices_as_of)}.`
            : ""}
        </p>
      ) : null}

      <div className="min-w-0">
        <HoldingsGrid
          config={config}
          data={data}
          filters={filters}
          fetching={q.fetching}
          switching={q.switching}
          noneYet={noneYet}
          addAction={
            <Link
              href={`/add/${config.type}`}
              className={buttonVariants({ size: "sm" })}
            >
              <Plus aria-hidden />
              {addLabel}
            </Link>
          }
          onFilters={q.setFilters}
          onReset={q.resetFilters}
          onSort={q.setSort}
          onPage={q.setPage}
          onEdit={onEdit}
          onDelete={onDelete}
        />

        <EditDialog
          config={config}
          row={editing}
          onClose={() => setEditing(null)}
          onSaved={handleSaved}
        />

        <DeleteDialog
          target={deleting}
          onClose={() => setDeleting(null)}
          onConfirm={handleDelete}
        />
      </div>
    </>
  );
}

/** Mutual funds: a Holdings · SIPs toggle (the `view` query param) above the grid or the SIP list. */
function MfPortfolio() {
  const router = useRouter();
  const pathname = usePathname();
  const view = useSearchParams().get("view") === "sips" ? "sips" : "holdings";
  return (
    <div className="space-y-4">
      <ToggleGroup
        aria-label="Mutual funds view"
        value={[view]}
        onValueChange={(v) => {
          const next = v[0];
          if (!next || next === view) return;
          router.replace(next === "sips" ? `${pathname}?view=sips` : pathname, {
            scroll: false,
          });
        }}
        variant="outline"
        size="sm"
        spacing={0}
        className="h-7"
      >
        <ToggleGroupItem value="holdings" className="h-7 px-3 text-[13.5px]">
          Holdings
        </ToggleGroupItem>
        <ToggleGroupItem value="sips" className="h-7 px-3 text-[13.5px]">
          SIPs
        </ToggleGroupItem>
      </ToggleGroup>
      {view === "sips" ? <SipGrid /> : <TypedPortfolio config={mfConfig} />}
    </div>
  );
}

export function Portfolio({ type }: { type: AssetType }) {
  switch (type) {
    case "fd":
      return <TypedPortfolio config={fdConfig} />;
    case "rd":
      return <TypedPortfolio config={rdConfig} />;
    case "stock":
      return <TypedPortfolio config={stockConfig} />;
    case "bond":
      return <TypedPortfolio config={bondConfig} />;
    case "mf":
      return <MfPortfolio />;
    case "gold":
      return <TypedPortfolio config={goldConfig} />;
    case "cash":
      return <TypedPortfolio config={cashConfig} />;
    case "pf":
      return <TypedPortfolio config={pfConfig} />;
    case "nps":
      return <TypedPortfolio config={npsConfig} />;
    case "other":
      return <TypedPortfolio config={otherConfig} />;
  }
}

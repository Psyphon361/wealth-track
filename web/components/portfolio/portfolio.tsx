"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Plus } from "lucide-react";
import { notify } from "@/lib/notify";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiDelete } from "@/lib/api";
import { getAssetEntry } from "@/lib/asset-catalog";
import { formatINR } from "@/lib/format";
import type { AssetType, HoldingRow, HoldingsSummary } from "@/lib/types";
import { addLabel as addLabelFor, refreshAssetTabCounts } from "./asset-tabs";
import { DeleteDialog, type DeleteTarget } from "./delete-dialog";
import { bondConfig } from "./grid/configs/bond";
import { fdConfig } from "./grid/configs/fd";
import { mfConfig } from "./grid/configs/mf";
import { rdConfig } from "./grid/configs/rd";
import { stockConfig } from "./grid/configs/stock";
import { HoldingsGrid, TableSkeleton } from "./grid/data-table";
import { GainCell } from "./grid/gain-cell";
import type { GridConfig } from "./grid/types";
import { hasActiveFilters, useHoldingsQuery } from "./grid/use-holdings-query";

const LABEL = "text-[11px] font-medium tracking-wider text-muted-foreground uppercase";

function SummaryStrip({ summary }: { summary: HoldingsSummary }) {
  return (
    <dl className="flex flex-wrap items-baseline gap-x-5 gap-y-1 text-sm">
      <div className="num font-medium">
        {summary.count} {summary.count === 1 ? "holding" : "holdings"}
      </div>
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
    </dl>
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
  const entry = getAssetEntry(config.type);
  const title = entry?.title ?? config.noun;
  const addLabel = addLabelFor(config.type);
  const count = q.data?.summary.count;

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
      .then((res) => notify.success(res))
      .catch((err: unknown) => {
        restore();
        notify.error(err);
      })
      .finally(refetch);
  }

  if (q.status === "loading") {
    return <TableSkeleton />;
  }

  if (q.status === "error" || !q.data) {
    return (
      <>
        <div className="flex flex-col items-start gap-3 rounded-lg border border-destructive/30 p-4">
          <div>
            <p className="text-sm font-medium text-destructive">
              {q.error?.message}
            </p>
            {q.error?.description ? (
              <p className="text-sm text-muted-foreground">
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

  if (data.summary.count === 0) {
    return (
      <>
        <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed py-16 text-center">
          <p className="text-lg font-medium">No {config.noun} yet</p>
          <Link
            href={`/add/${config.type}`}
            className={buttonVariants({ size: "sm" })}
          >
            <Plus aria-hidden />
            {addLabel}
          </Link>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SummaryStrip summary={data.summary} />
        <Link
          href={`/add/${config.type}`}
          className={buttonVariants({ size: "sm" })}
        >
          <Plus aria-hidden />
          {addLabel}
        </Link>
      </div>

      <div className="min-w-0">
        <HoldingsGrid
          config={config}
          data={data}
          filters={filters}
          fetching={q.fetching}
          onFilters={q.setFilters}
          onReset={q.resetFilters}
          onSort={q.setSort}
          onPage={q.setPage}
          onEdit={onEdit}
          onDelete={onDelete}
        />

        <Dialog
          open={editing !== null}
          onOpenChange={(open) => {
            if (!open) setEditing(null);
          }}
        >
          <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
            <DialogHeader>
              <DialogTitle>Edit {title.toLowerCase()}</DialogTitle>
              <DialogDescription>
                {editing ? config.rowName(editing) : ""}
              </DialogDescription>
            </DialogHeader>
            {editing ? config.renderEditForm(editing, handleSaved) : null}
          </DialogContent>
        </Dialog>

        <DeleteDialog
          target={deleting}
          onClose={() => setDeleting(null)}
          onConfirm={handleDelete}
        />
      </div>
    </>
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
      return <TypedPortfolio config={mfConfig} />;
  }
}

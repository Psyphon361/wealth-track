"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { RefreshCw } from "lucide-react";
import { notify } from "@/lib/notify";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { AssetForm } from "@/components/forms/asset-form";
import { apiDelete, apiGet, toApiMessage } from "@/lib/api";
import {
  ASSET_TYPE_LABELS,
  type AssetRecord,
  type AssetType,
  type Bond,
  type FixedDeposit,
  type MutualFund,
  type PortfolioGroup,
  type PortfolioItem,
  type PortfolioResponse,
  type RecurringDeposit,
  type Stock,
} from "@/lib/types";
import {
  bondColumns,
  fdColumns,
  itemName,
  mfColumns,
  rdColumns,
  stockColumns,
  type Row,
} from "./columns";
import { DeleteDialog, type DeleteTarget } from "./delete-dialog";
import { GroupTable } from "./group-table";

type State =
  | { status: "loading" }
  | { status: "error"; message: string; description: string }
  | { status: "ready"; data: PortfolioResponse };

type Target = DeleteTarget;

function EditForm({
  target,
  onSaved,
}: {
  target: Target;
  onSaved: (record: AssetRecord) => void;
}) {
  const key = `${target.type}-${target.item.id}`;
  switch (target.type) {
    case "fd":
      return (
        <AssetForm
          key={key}
          type="fd"
          record={target.item as FixedDeposit}
          onSaved={onSaved}
        />
      );
    case "rd":
      return (
        <AssetForm
          key={key}
          type="rd"
          record={target.item as RecurringDeposit}
          onSaved={onSaved}
        />
      );
    case "stock":
      return (
        <AssetForm
          key={key}
          type="stock"
          record={target.item as Stock}
          onSaved={onSaved}
        />
      );
    case "bond":
      return (
        <AssetForm
          key={key}
          type="bond"
          record={target.item as Bond}
          onSaved={onSaved}
        />
      );
    case "mf":
      return (
        <AssetForm
          key={key}
          type="mf"
          record={target.item as MutualFund}
          onSaved={onSaved}
        />
      );
  }
}

function removeItem(
  data: PortfolioResponse,
  type: AssetType,
  id: number,
): PortfolioResponse {
  return {
    groups: data.groups
      .map((g) => {
        if (g.type !== type) return g;
        const removed = g.items.find((i) => i.id === id);
        if (!removed) return g;
        const items = g.items.filter((i) => i.id !== id);
        const invested = g.totals.invested - removed.invested;
        const current = g.totals.current_value - removed.current_value;
        const gain = current - invested;
        return {
          ...g,
          items,
          totals: {
            invested,
            current_value: current,
            gain,
            gain_pct: invested > 0 ? (gain / invested) * 100 : 0,
          },
        };
      })
      .filter((g) => g.items.length > 0),
  };
}

function mergeItem(
  data: PortfolioResponse,
  type: AssetType,
  saved: AssetRecord,
): PortfolioResponse {
  return {
    groups: data.groups.map((g) =>
      g.type !== type
        ? g
        : {
            ...g,
            items: g.items.map((i) =>
              i.id === saved.id ? ({ ...i, ...saved } as PortfolioItem) : i,
            ),
          },
    ),
  };
}

export function Portfolio() {
  const [state, setState] = useState<State>({ status: "loading" });
  const [refreshing, setRefreshing] = useState(false);
  const [updatingIds, setUpdatingIds] = useState<ReadonlySet<number>>(
    () => new Set<number>(),
  );
  const [editing, setEditing] = useState<Target | null>(null);
  const [deleting, setDeleting] = useState<Target | null>(null);
  const requestId = useRef(0);
  const hasData = useRef(false);

  const load = useCallback(() => {
    const id = ++requestId.current;
    apiGet<PortfolioResponse>("/portfolio")
      .then((data) => {
        if (id !== requestId.current) return;
        hasData.current = true;
        setState({ status: "ready", data });
        setRefreshing(false);
        setUpdatingIds(new Set<number>());
      })
      .catch((err: unknown) => {
        if (id !== requestId.current) return;
        const { message, description } = toApiMessage(err);
        setRefreshing(false);
        setUpdatingIds(new Set<number>());
        if (hasData.current) notify.error(err);
        else setState({ status: "error", message, description });
      });
  }, []);

  useEffect(() => {
    const counter = requestId;
    load();
    return () => {
      counter.current++;
    };
  }, [load]);

  function refresh() {
    setRefreshing(true);
    load();
  }

  function retry() {
    setState({ status: "loading" });
    load();
  }

  function handleSaved(saved: AssetRecord) {
    if (!editing || state.status !== "ready") return;
    const { type } = editing;
    setEditing(null);
    setState({ status: "ready", data: mergeItem(state.data, type, saved) });
    setUpdatingIds((prev) => new Set(prev).add(saved.id));
    refresh();
  }

  function handleDelete(target: Target) {
    setDeleting(null);
    if (state.status !== "ready") return;
    const previous = state;
    // Invalidate any in-flight refresh so a stale list can't reappear.
    requestId.current++;
    setState({
      status: "ready",
      data: removeItem(state.data, target.type, target.item.id),
    });
    apiDelete(`/assets/${target.type}/${target.item.id}`)
      .then((res) => notify.success(res))
      .catch((err: unknown) => {
        setState(previous);
        notify.error(err);
      })
      .finally(refresh);
  }

  if (state.status === "loading") {
    return (
      <div className="space-y-3" aria-busy="true" aria-label="Loading…">
        <Skeleton className="h-48 rounded-xl" />
        <Skeleton className="h-48 rounded-xl" />
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="flex flex-col items-start gap-3 rounded-lg border border-destructive/30 p-4">
        <div>
          <p className="text-sm font-medium text-destructive">{state.message}</p>
          {state.description && (
            <p className="text-sm text-muted-foreground">{state.description}</p>
          )}
        </div>
        <Button variant="outline" onClick={retry}>
          Retry
        </Button>
      </div>
    );
  }

  const groups = state.data.groups.filter((g) => g.items.length > 0);
  if (groups.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed py-16 text-center">
        <p className="text-lg font-medium">No holdings yet</p>
        <p className="text-sm text-muted-foreground">
          Add your first holding to see it here.
        </p>
        <Link href="/add" className={buttonVariants()}>
          Add a holding
        </Link>
      </div>
    );
  }

  function renderGroup(g: PortfolioGroup) {
    const type = g.type;
    const onEdit = (item: PortfolioItem) => setEditing({ type, item });
    const onDelete = (item: PortfolioItem) => setDeleting({ type, item });
    switch (type) {
      case "fd":
        return (
          <GroupTable
            key={type}
            group={g}
            items={g.items as Row<FixedDeposit>[]}
            columns={fdColumns}
            onEdit={onEdit}
            onDelete={onDelete}
            updatingIds={updatingIds}
          />
        );
      case "rd":
        return (
          <GroupTable
            key={type}
            group={g}
            items={g.items as Row<RecurringDeposit>[]}
            columns={rdColumns}
            onEdit={onEdit}
            onDelete={onDelete}
            updatingIds={updatingIds}
          />
        );
      case "stock":
        return (
          <GroupTable
            key={type}
            group={g}
            items={g.items as Row<Stock>[]}
            columns={stockColumns}
            onEdit={onEdit}
            onDelete={onDelete}
            updatingIds={updatingIds}
          />
        );
      case "bond":
        return (
          <GroupTable
            key={type}
            group={g}
            items={g.items as Row<Bond>[]}
            columns={bondColumns}
            onEdit={onEdit}
            onDelete={onDelete}
            updatingIds={updatingIds}
          />
        );
      case "mf":
        return (
          <GroupTable
            key={type}
            group={g}
            items={g.items as Row<MutualFund>[]}
            columns={mfColumns}
            onEdit={onEdit}
            onDelete={onDelete}
            updatingIds={updatingIds}
          />
        );
    }
  }

  return (
    <div className="space-y-3">
      <div
        role="status"
        aria-live="polite"
        className="flex h-4 items-center justify-end gap-1.5 text-xs text-muted-foreground"
      >
        {refreshing ? (
          <>
            <RefreshCw className="size-3 animate-spin" />
            Refreshing
          </>
        ) : null}
      </div>
      {groups.map(renderGroup)}

      <Dialog
        open={editing !== null}
        onOpenChange={(open) => {
          if (!open) setEditing(null);
        }}
      >
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              Edit {editing ? ASSET_TYPE_LABELS[editing.type] : ""}
            </DialogTitle>
            <DialogDescription>
              {editing ? itemName(editing.item) : ""}
            </DialogDescription>
          </DialogHeader>
          {editing ? <EditForm target={editing} onSaved={handleSaved} /> : null}
        </DialogContent>
      </Dialog>

      <DeleteDialog
        target={deleting}
        onClose={() => setDeleting(null)}
        onConfirm={handleDelete}
      />
    </div>
  );
}

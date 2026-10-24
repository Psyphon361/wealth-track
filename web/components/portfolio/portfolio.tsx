"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { AssetForm } from "@/components/forms/asset-form";
import { apiDelete, apiGet } from "@/lib/api";
import {
  ASSET_TYPE_LABELS,
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
import { GroupTable } from "./group-table";

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: PortfolioResponse };

interface Target {
  type: AssetType;
  item: PortfolioItem;
}

function Skeleton({ className }: { className: string }) {
  return <div className={`animate-pulse rounded-lg bg-muted ${className}`} />;
}

function EditForm({
  target,
  onSaved,
}: {
  target: Target;
  onSaved: () => void;
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

export function Portfolio() {
  const [state, setState] = useState<State>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [editing, setEditing] = useState<Target | null>(null);
  const [deleting, setDeleting] = useState<Target | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiGet<PortfolioResponse>("/portfolio")
      .then((data) => {
        if (!cancelled) setState({ status: "ready", data });
      })
      .catch((err: unknown) => {
        if (!cancelled)
          setState({
            status: "error",
            message:
              err instanceof Error ? err.message : "Failed to load portfolio",
          });
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const refetch = useCallback(() => setAttempt((a) => a + 1), []);

  function retry() {
    setState({ status: "loading" });
    refetch();
  }

  function handleSaved() {
    setEditing(null);
    refetch();
  }

  async function confirmDelete() {
    if (!deleting) return;
    const target = deleting;
    setBusy(true);
    try {
      await apiDelete(`/assets/${target.type}/${target.item.id}`);
      toast.success(`Deleted ${itemName(target.item)}`);
      setDeleting(null);
      refetch();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to delete");
    } finally {
      setBusy(false);
    }
  }

  if (state.status === "loading") {
    return (
      <div className="space-y-6" aria-busy="true" aria-label="Loading…">
        <Skeleton className="h-48" />
        <Skeleton className="h-48" />
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="flex flex-col items-start gap-3 rounded-lg border border-destructive/30 p-4">
        <p className="text-sm text-destructive">{state.message}</p>
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
          />
        );
    }
  }

  return (
    <div className="space-y-8">
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

      <AlertDialog
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open && !busy) setDeleting(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Delete {deleting ? itemName(deleting.item) : ""}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              This can&apos;t be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={busy}
              onClick={confirmDelete}
            >
              {busy ? "Deleting…" : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

"use client";

import { useState } from "react";
import { toast } from "sonner";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { apiDelete } from "@/lib/api";
import type { AssetType, PortfolioItem } from "@/lib/types";
import { itemName } from "./columns";

export interface DeleteTarget {
  type: AssetType;
  item: PortfolioItem;
}

/**
 * Controlled confirm dialog. The confirm button is a plain button (not a
 * dialog "close" part), so the dialog stays mounted and pending while the
 * request is awaited; only afterwards do we close, toast and refetch.
 */
export function DeleteDialog({
  target,
  onClose,
  onDeleted,
}: {
  target: DeleteTarget | null;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [pending, setPending] = useState(false);

  async function confirm() {
    if (!target || pending) return;
    setPending(true);
    try {
      await apiDelete(`/assets/${target.type}/${target.item.id}`);
      toast.success(`Deleted ${itemName(target.item)}`);
      onDeleted();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to delete");
    } finally {
      setPending(false);
    }
  }

  return (
    <AlertDialog
      open={target !== null}
      onOpenChange={(open) => {
        if (!open && !pending) onClose();
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            Delete {target ? itemName(target.item) : ""}?
          </AlertDialogTitle>
          <AlertDialogDescription>
            This can&apos;t be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>Cancel</AlertDialogCancel>
          <Button
            type="button"
            variant="destructive"
            disabled={pending}
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              void confirm();
            }}
          >
            {pending ? "Deleting…" : "Delete"}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

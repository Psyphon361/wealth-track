"use client";

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
import type { AssetType, PortfolioItem } from "@/lib/types";
import { itemName } from "./columns";

export interface DeleteTarget {
  type: AssetType;
  item: PortfolioItem;
}

/**
 * Controlled confirm dialog. Confirming closes immediately; the parent
 * performs the (optimistic) delete.
 */
export function DeleteDialog({
  target,
  onClose,
  onConfirm,
}: {
  target: DeleteTarget | null;
  onClose: () => void;
  onConfirm: (target: DeleteTarget) => void;
}) {
  return (
    <AlertDialog
      open={target !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
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
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <Button
            type="button"
            variant="destructive"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              if (target) onConfirm(target);
            }}
          >
            Delete
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

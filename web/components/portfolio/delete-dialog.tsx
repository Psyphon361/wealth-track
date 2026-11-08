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
import { useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { AssetType } from "@/lib/types";

export interface DeleteTarget {
  type: AssetType;
  id: number;
  name: string;
  /** The holding was paid from a cash account (deleting refunds it). */
  paidFrom?: boolean;
}

/**
 * Controlled confirm dialog. By default confirming closes it and the parent
 * shows the pending state; with `pending` set the dialog stays open, shows
 * "Deleting…", disables both buttons and ignores Escape and overlay clicks.
 */
export function DeleteDialog({
  target,
  pending = false,
  onClose,
  onConfirm,
}: {
  target: DeleteTarget | null;
  pending?: boolean;
  onClose: () => void;
  onConfirm: (target: DeleteTarget) => void;
}) {
  // Keep the last name while the dialog animates closed.
  const [lastName, setLastName] = useState("");
  if (target && target.name !== lastName) setLastName(target.name);
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
            Delete {target ? target.name : lastName}?
          </AlertDialogTitle>
          <AlertDialogDescription>
            It moves to Recently deleted and is permanently deleted after 30 days. Restore it from there if you need it.
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
              if (target && !pending) onConfirm(target);
            }}
          >
            {pending ? <Loader2 className="size-3.5 animate-spin" /> : null}
            {pending ? "Deleting…" : "Delete"}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

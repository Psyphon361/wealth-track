"use client";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { getAssetEntry } from "@/lib/asset-catalog";
import type { HoldingRow } from "@/lib/types";
import type { GridConfig } from "./grid/types";

/** Edit dialog shared by the grid and the holding details page. */
export function EditDialog<TRow extends HoldingRow>({
  config,
  row,
  onClose,
  onSaved,
}: {
  config: GridConfig<TRow>;
  row: TRow | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const title = getAssetEntry(config.type)?.title ?? config.noun;
  return (
    <Dialog
      open={row !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Edit {title.toLowerCase()}</DialogTitle>
          <DialogDescription>{row ? config.rowName(row) : ""}</DialogDescription>
        </DialogHeader>
        {row ? config.renderEditForm(row, onSaved) : null}
      </DialogContent>
    </Dialog>
  );
}

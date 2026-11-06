"use client";

import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DuplicateDialog, type DuplicateDialogProps } from "./duplicate-dialog";
import { FormDisabledContext, useReportBusy } from "./form-disabled";

export function FormShell({
  onSubmit,
  saving,
  editing,
  onCancel,
  duplicate,
  submitLabel,
  children,
}: {
  onSubmit: React.FormEventHandler<HTMLFormElement>;
  saving: boolean;
  editing: boolean;
  onCancel?: () => void;
  /** Duplicate warning dialog state from useAssetSave. */
  duplicate?: DuplicateDialogProps;
  /** Submit button text when not saving (default: "Add asset" / "Save changes"). */
  submitLabel?: string;
  children: React.ReactNode;
}) {
  useReportBusy(saving);
  return (
    <>
      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-5">
        <FormDisabledContext.Provider value={saving}>
          <fieldset disabled={saving} className="contents">
            <div className="grid gap-x-6 gap-y-3 sm:grid-cols-2">{children}</div>
          </fieldset>
        </FormDisabledContext.Provider>
        <div className="flex items-center justify-end gap-2 pt-2">
          {onCancel ? (
            <Button
              type="button"
              variant="ghost"
              onClick={onCancel}
              disabled={saving}
            >
              Cancel
            </Button>
          ) : null}
          <Button type="submit" disabled={saving}>
            {saving ? <Loader2 className="size-3.5 animate-spin" /> : null}
            {saving
              ? "Saving…"
              : (submitLabel ?? (editing ? "Save changes" : "Add asset"))}
          </Button>
        </div>
      </form>
      {duplicate ? <DuplicateDialog {...duplicate} /> : null}
    </>
  );
}

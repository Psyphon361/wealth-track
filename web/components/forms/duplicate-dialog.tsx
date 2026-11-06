"use client";

import { useState } from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";
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
import { readDuplicates, type DuplicateMatch } from "@/lib/duplicates";

export interface DuplicateDialogProps {
  open: boolean;
  /** API title and body text of the 409. */
  message: string;
  description: string;
  matches: DuplicateMatch[];
  /** Details page of an existing holding. */
  hrefFor: (match: DuplicateMatch) => string;
  /** True while the "Add anyway" request runs. */
  pending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

/**
 * Warning shown when the API answers 409 "looks like a holding you already
 * have". Cancel leaves the form filled; "Add anyway" retries the create.
 */
export function DuplicateDialog({
  open,
  message,
  description,
  matches,
  hrefFor,
  pending,
  onCancel,
  onConfirm,
}: DuplicateDialogProps) {
  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !pending) onCancel();
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{message}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        {matches.length ? (
          <ul className="flex flex-col gap-1 text-[13.5px]">
            {matches.map((m) => (
              <li key={m.id}>
                <Link
                  href={hrefFor(m)}
                  onClick={onCancel}
                  className="underline underline-offset-3 hover:text-foreground"
                >
                  {m.name}
                </Link>
              </li>
            ))}
          </ul>
        ) : null}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>Cancel</AlertDialogCancel>
          <Button
            type="button"
            disabled={pending}
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onConfirm();
            }}
          >
            {pending ? <Loader2 className="size-3.5 animate-spin" /> : null}
            {pending ? "Adding…" : "Add anyway"}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

interface Pending {
  message: string;
  description: string;
  matches: DuplicateMatch[];
  retry: () => Promise<void>;
}

/**
 * State for a DuplicateDialog. Call `intercept(error, retry)` in a create
 * failure path: when the error is a duplicate warning it opens the dialog
 * (returns true, show no toast); "Add anyway" then awaits `retry`, which must
 * do the confirmed request and its own success/error handling. The dialog
 * closes when `retry` settles. `busy` is true while it runs.
 */
export function useDuplicateWarning(hrefFor: (m: DuplicateMatch) => string) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  // Kept after closing so the text doesn't vanish during the exit animation.
  const [shown, setShown] = useState<Pending | null>(null);

  function intercept(err: unknown, retry: () => Promise<void>): boolean {
    const matches = readDuplicates(err);
    if (!matches) return false;
    const e = err as Error & { description?: string };
    setShown({
      message: e.message,
      description: e.description ?? "",
      matches,
      retry,
    });
    setOpen(true);
    return true;
  }

  async function confirm() {
    if (!shown || busy) return;
    setBusy(true);
    try {
      await shown.retry();
    } finally {
      setBusy(false);
      setOpen(false);
    }
  }

  const props: DuplicateDialogProps = {
    open,
    message: shown?.message ?? "",
    description: shown?.description ?? "",
    matches: shown?.matches ?? [],
    hrefFor,
    pending: busy,
    onCancel: () => setOpen(false),
    onConfirm: () => void confirm(),
  };

  return { props, intercept, busy };
}

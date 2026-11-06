"use client";

import { useState, type ReactNode } from "react";
import {
  Ban,
  Loader2,
  MoreHorizontal,
  Pause,
  Pencil,
  Play,
  SkipForward,
  Trash2,
  Undo2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { apiDelete, apiPost, type ApiMessage } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { markHoldingsStale } from "@/lib/holdings-cache";
import { notify } from "@/lib/notify";
import {
  ACTION_LABELS,
  actionPath,
  availableActions,
  type SipActionKey,
} from "@/lib/sip";
import type { Sip } from "@/lib/types";
import { SipEditDialog } from "./sip-edit-dialog";

const ICONS: Record<SipActionKey, ReactNode> = {
  edit: <Pencil />,
  skip: <SkipForward />,
  undo: <Undo2 />,
  pause: <Pause />,
  resume: <Play />,
  stop: <Ban />,
  delete: <Trash2 />,
};

type ConfirmKey = "skip" | "stop" | "delete";

interface ConfirmText {
  title: string;
  description: string;
  cancel: string;
  confirm: string;
  pending: string;
  destructive: boolean;
}

function confirmText(key: ConfirmKey, sip: Sip): ConfirmText {
  switch (key) {
    case "skip":
      return {
        title: `Skip the ${sip.next_date ? formatDate(sip.next_date) : "next"} instalment?`,
        description:
          "No units are added for that date. Later instalments carry on as usual. You can undo this until the date.",
        cancel: "Cancel",
        confirm: "Skip Instalment",
        pending: "Skipping…",
        destructive: false,
      };
    case "stop":
      return {
        title: `Cancel the ${sip.fund_name} SIP?`,
        description:
          "No more instalments are added. Instalments already added stay in your holding.",
        cancel: "Keep SIP",
        confirm: "Cancel SIP",
        pending: "Cancelling…",
        destructive: true,
      };
    case "delete":
      return {
        title: `Delete the ${sip.fund_name} SIP?`,
        description:
          "It is removed from your SIPs list. Instalments already added stay in your holding.",
        cancel: "Cancel",
        confirm: "Delete",
        pending: "Deleting…",
        destructive: true,
      };
  }
}

function ConfirmDialog({
  action,
  sip,
  pending,
  onClose,
  onConfirm,
}: {
  action: ConfirmKey | null;
  sip: Sip;
  pending: boolean;
  onClose: () => void;
  onConfirm: (action: ConfirmKey) => void;
}) {
  // Kept after closing so the text doesn't change during the exit animation.
  const [shown, setShown] = useState<ConfirmKey>("skip");
  const [prev, setPrev] = useState<ConfirmKey | null>(null);
  if (action !== prev) {
    setPrev(action);
    if (action) setShown(action);
  }
  const text = confirmText(shown, sip);
  return (
    <AlertDialog
      open={action !== null}
      onOpenChange={(open) => {
        if (!open && !pending) onClose();
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{text.title}</AlertDialogTitle>
          <AlertDialogDescription>{text.description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>{text.cancel}</AlertDialogCancel>
          <Button
            type="button"
            variant={text.destructive ? "destructive" : "default"}
            disabled={pending}
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onConfirm(shown);
            }}
          >
            {pending ? <Loader2 className="size-3.5 animate-spin" /> : null}
            {pending ? text.pending : text.confirm}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

/**
 * Actions menu of one SIP (Update, Skip Next / Undo Skip, Pause / Resume,
 * Cancel, Delete) with confirm dialogs. Toasts come from the API; `onChanged`
 * runs after every successful change so the caller reloads.
 */
export function SipActions({
  sip,
  onChanged,
  showLabel = false,
}: {
  sip: Sip;
  onChanged: () => void;
  /** Show a text button ("Manage SIP") instead of the icon button. */
  showLabel?: boolean;
}) {
  const [confirm, setConfirm] = useState<ConfirmKey | null>(null);
  const [editing, setEditing] = useState(false);
  const [pending, setPending] = useState<SipActionKey | null>(null);

  async function run(
    key: SipActionKey,
    request: () => Promise<ApiMessage | undefined>,
  ) {
    setPending(key);
    try {
      notify.success(await request());
    } catch (e) {
      notify.error(e);
    } finally {
      setPending(null);
      setConfirm(null);
      // Reload either way: a failed action usually means the SIP changed meanwhile.
      markHoldingsStale("mf");
      onChanged();
    }
  }

  function perform(key: SipActionKey) {
    switch (key) {
      case "edit":
        setEditing(true);
        return;
      case "skip":
      case "stop":
      case "delete":
        setConfirm(key);
        return;
      case "undo":
        void run(key, () => apiDelete(actionPath(sip, "undo")));
        return;
      case "pause":
      case "resume":
        void run(key, () => apiPost<ApiMessage>(actionPath(sip, key), {}));
        return;
    }
  }

  function confirmed(key: ConfirmKey) {
    if (key === "delete") {
      void run(key, () => apiDelete(`/sips/${sip.id}`));
    } else {
      void run(key, () => apiPost<ApiMessage>(actionPath(sip, key), {}));
    }
  }

  const actions = availableActions(sip);
  const busy = pending !== null;

  return (
    <>
      {busy && confirm === null ? (
        <Button
          type="button"
          variant={showLabel ? "outline" : "ghost"}
          size={showLabel ? "sm" : "icon-xs"}
          disabled
          aria-label="Saving…"
          className="text-muted-foreground"
        >
          <Loader2 className="animate-spin" aria-hidden />
          {showLabel ? "Saving…" : null}
        </Button>
      ) : (
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                type="button"
                variant={showLabel ? "outline" : "ghost"}
                size={showLabel ? "sm" : "icon-xs"}
                aria-label={showLabel ? undefined : "SIP actions"}
                className={
                  showLabel
                    ? undefined
                    : "text-muted-foreground hover:text-foreground"
                }
              />
            }
          >
            <MoreHorizontal aria-hidden />
            {showLabel ? "Manage SIP" : null}
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-40">
            {actions.map((key, i) => (
              <div key={key} className="contents">
                {i > 0 && (key === "stop" || key === "delete") ? (
                  <DropdownMenuSeparator />
                ) : null}
                <DropdownMenuItem
                  variant={key === "stop" || key === "delete" ? "destructive" : "default"}
                  onClick={() => perform(key)}
                >
                  {ICONS[key]}
                  {ACTION_LABELS[key]}
                </DropdownMenuItem>
              </div>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
      <ConfirmDialog
        action={confirm}
        sip={sip}
        pending={busy}
        onClose={() => setConfirm(null)}
        onConfirm={confirmed}
      />
      <SipEditDialog
        sip={sip}
        open={editing}
        onClose={() => setEditing(false)}
        onSaved={() => {
          setEditing(false);
          onChanged();
        }}
      />
    </>
  );
}

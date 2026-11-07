"use client";

import { useEffect, useState } from "react";
import { Loader2, Undo2 } from "lucide-react";
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
import { Card } from "@/components/ui/card";
import { afterExit } from "@/components/exits/after-exit";
import { ReinvestMenu } from "@/components/exits/reinvest";
import { useCashAccounts } from "@/components/exits/use-cash-accounts";
import { gainTone } from "@/components/portfolio/grid/gain-cell";
import { apiDelete, apiGet, toApiMessage, type ApiMessage } from "@/lib/api";
import {
  canReinvest,
  exitGain,
  exitTitle,
  exitWhere,
  reinvestSummary,
  undoableExitId,
  type CashAccount,
  type ExitRead,
} from "@/lib/exits";
import { formatDate } from "@/lib/format";
import { notify } from "@/lib/notify";
import { amountText } from "@/lib/sip";
import type { AssetType } from "@/lib/types";
import { cn } from "@/lib/utils";
import { LABEL } from "./sections";

function monthAndDay(iso: string): { month: string; day: number } {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  const month = new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", {
    month: "short",
    timeZone: "UTC",
  });
  return { month, day: d };
}

function UndoDialog({
  exit,
  pending,
  onClose,
  onConfirm,
}: {
  exit: ExitRead | null;
  pending: boolean;
  onClose: () => void;
  onConfirm: (exit: ExitRead) => void;
}) {
  // Kept after closing so the text doesn't change during the exit animation.
  const [shown, setShown] = useState<ExitRead | null>(null);
  const [prev, setPrev] = useState<ExitRead | null>(null);
  if (exit !== prev) {
    setPrev(exit);
    if (exit) setShown(exit);
  }
  const sale = shown?.kind !== "maturity";
  return (
    <AlertDialog
      open={exit !== null}
      onOpenChange={(open) => {
        if (!open && !pending) onClose();
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {sale ? "Undo this sale?" : "Undo this settlement?"}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {sale
              ? "The holding comes back as it was before the sale. Money added to a cash account is taken out again."
              : "The holding goes back to Matured. Money added to a cash account is taken out again."}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>Keep It</AlertDialogCancel>
          <Button
            type="button"
            disabled={pending}
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              if (shown) onConfirm(shown);
            }}
          >
            {pending ? <Loader2 className="size-3.5 animate-spin" /> : null}
            {pending ? "Undoing…" : "Undo"}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function ExitRows({
  type,
  exits,
  onUndone,
}: {
  type: AssetType;
  exits: ExitRead[];
  onUndone: () => void;
}) {
  const { accounts } = useCashAccounts();
  const [confirming, setConfirming] = useState<ExitRead | null>(null);
  const [pending, setPending] = useState(false);
  const latest = undoableExitId(exits);

  function accountName(list: CashAccount[] | null, id: number | null): string | null {
    if (id === null) return null;
    return list?.find((a) => a.id === id)?.name ?? null;
  }

  async function undo(exit: ExitRead) {
    setPending(true);
    try {
      const res = await apiDelete(`/exits/${exit.id}`);
      afterExit(type, exit);
      notify.success(res);
    } catch (e) {
      notify.error(e);
    } finally {
      setPending(false);
      setConfirming(null);
      // Reload either way: a failed undo usually means the holding changed meanwhile.
      onUndone();
    }
  }

  return (
    <>
      <ul className="flex flex-col divide-y divide-border/50">
        {exits.map((exit) => {
          const { month, day } = monthAndDay(exit.date);
          const cashName = accountName(accounts, exit.cash_holding_id);
          const where = exitWhere(exit, cashName);
          const summary = reinvestSummary(exit, cashName);
          const gain = exitGain(exit);
          return (
            <li
              key={exit.id}
              className="flex items-start gap-3 py-2.5 first:pt-0 last:pb-0"
            >
              <div
                aria-hidden
                className="flex size-10 shrink-0 flex-col items-center justify-center rounded-lg bg-muted leading-none"
              >
                <span className="text-[10px] tracking-wider text-muted-foreground uppercase">
                  {month}
                </span>
                <span className="num mt-0.5 text-sm font-medium">{day}</span>
              </div>
              <div className="min-w-0 flex-1 space-y-0.5">
                <p className="text-[13.5px] font-medium">
                  {exitTitle(type, exit)}
                  <span className="font-normal text-muted-foreground">
                    {" "}
                    · {formatDate(exit.date)}
                  </span>
                </p>
                <p className="text-[13.2px] text-muted-foreground">{where.text}</p>
                {summary ? (
                  <p className="num text-[13.2px] text-muted-foreground">{summary}</p>
                ) : null}
              </div>
              <div className="text-right">
                <p className="num text-[13.5px] font-medium">
                  {amountText(exit.amount)}
                </p>
                {gain ? (
                  <p className={cn("num text-[13.2px]", gainTone(gain.value))}>
                    {gain.text}
                  </p>
                ) : null}
              </div>
              {canReinvest(exit) ? (
                <ReinvestMenu exit={exit} cashName={cashName ?? "your account"} />
              ) : null}
              {exit.id === latest ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={pending}
                  onClick={() => setConfirming(exit)}
                >
                  <Undo2 aria-hidden />
                  Undo
                </Button>
              ) : null}
            </li>
          );
        })}
      </ul>
      <UndoDialog
        exit={confirming}
        pending={pending}
        onClose={() => setConfirming(null)}
        onConfirm={(exit) => void undo(exit)}
      />
    </>
  );
}

/**
 * Sales and settlements of one holding, newest first, with Undo on the latest one. Renders
 * nothing when there are none. `version` changes to reload after a sale or settlement.
 */
export function ExitsSection({
  type,
  id,
  version,
  onChanged,
}: {
  type: AssetType;
  id: number;
  version: number;
  onChanged: () => void;
}) {
  const [exits, setExits] = useState<ExitRead[] | null>(null);
  const [error, setError] = useState<ApiMessage | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    apiGet<ExitRead[]>(`/holdings/${type}/${id}/exits`)
      .then((list) => {
        if (cancelled) return;
        setExits(list);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(toApiMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [type, id, version, attempt]);

  if (error && !exits) {
    return (
      <Card size="sm" className="gap-3 px-4">
        <h3 className={LABEL}>Sales and settlements</h3>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-[13.5px] font-medium text-destructive">{error.message}</p>
            {error.description ? (
              <p className="text-[13.2px] text-muted-foreground">{error.description}</p>
            ) : null}
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setError(null);
              setAttempt((n) => n + 1);
            }}
          >
            Retry
          </Button>
        </div>
      </Card>
    );
  }
  // Nothing to show while loading or when the holding was never sold or settled.
  if (!exits || exits.length === 0) return null;
  return (
    <Card size="sm" className="gap-3 px-4">
      <h3 className={LABEL}>Sales and settlements</h3>
      <ExitRows type={type} exits={exits} onUndone={onChanged} />
    </Card>
  );
}

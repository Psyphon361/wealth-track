"use client";

import { ChevronDown } from "lucide-react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  REINVEST_QUESTION,
  REINVEST_TYPES,
  reinvestPrefillFor,
  successLine,
  type ExitRead,
} from "@/lib/exits";
import { setReinvest } from "@/lib/reinvest";

type ReinvestExit = Pick<
  ExitRead,
  "id" | "date" | "amount" | "cash_holding_id" | "cash_added" | "left_in_account"
>;

/** Remembers the prefill for `type` and opens its add form; "More…" (type null) keeps it for any type and opens /add. */
export function useGoReinvest(exit: ReinvestExit, cashName: string) {
  const router = useRouter();
  return (type: string | null, beforeGo?: () => void) => {
    if (type === null) {
      const p = reinvestPrefillFor("*", exit, cashName);
      if (p) setReinvest(p);
      beforeGo?.();
      router.push("/add");
      return;
    }
    const prefill = reinvestPrefillFor(type, exit, cashName);
    if (!prefill) return;
    setReinvest(prefill);
    beforeGo?.();
    router.push(`/add/${type}`);
  };
}

/**
 * Last step of a sale or settlement that put money in an account: where it is now, and quick
 * buttons to add a holding paid from it.
 */
export function ExitSuccess({
  exit,
  cashName,
  onDone,
}: {
  exit: ExitRead;
  cashName: string;
  /** Closes the dialog and refreshes the page; also runs before leaving for an add form. */
  onDone: () => void;
}) {
  const go = useGoReinvest(exit, cashName);
  return (
    <div className="flex flex-col gap-4">
      <div>
        <p className="num text-[13.5px] font-medium">{successLine(exit, cashName)}</p>
        <p className="text-[13.2px] text-muted-foreground">{REINVEST_QUESTION}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        {REINVEST_TYPES.map((t) => (
          <Button
            key={t.type}
            type="button"
            variant="outline"
            size="sm"
            onClick={() => go(t.type, onDone)}
          >
            {t.label}
          </Button>
        ))}
        <Button type="button" variant="outline" size="sm" onClick={() => go(null, onDone)}>
          More…
        </Button>
      </div>
      <div className="flex justify-end pt-2">
        <Button type="button" onClick={onDone}>
          Done
        </Button>
      </div>
    </div>
  );
}

/** Small "Reinvest" menu of asset types for one exit on the details page. */
export function ReinvestMenu({
  exit,
  cashName,
}: {
  exit: ReinvestExit;
  cashName: string;
}) {
  const go = useGoReinvest(exit, cashName);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={<Button type="button" variant="outline" size="sm" />}>
        Reinvest
        <ChevronDown aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-40">
        {REINVEST_TYPES.map((t) => (
          <DropdownMenuItem key={t.type} onClick={() => go(t.type)}>
            {t.label}
          </DropdownMenuItem>
        ))}
        <DropdownMenuItem onClick={() => go(null)}>More…</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

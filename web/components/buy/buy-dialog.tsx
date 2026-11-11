"use client";

import { useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useDuplicateWarning } from "@/components/forms/duplicate-dialog";
import { DateField, TextField } from "@/components/forms/fields";
import { FormBusyContext } from "@/components/forms/form-disabled";
import { FormShell } from "@/components/forms/form-shell";
import { todayISO } from "@/components/forms/schema";
import { fieldIssues } from "@/components/forms/use-asset-form";
import { useNavAutofill } from "@/components/forms/use-nav-autofill";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiPost } from "@/lib/api";
import {
  BUY_INFO_LINE,
  BUY_UNITS_HINT,
  buyAmount,
  buyBody,
  buyDate,
  buyDateError,
  buyNav,
  buyPath,
  buyUnits,
  lastSaleDate,
  previewUnits,
  type BuyResult,
} from "@/lib/buy";
import { confirmDuplicatePath, duplicateHref } from "@/lib/duplicates";
import { markHoldingsStale } from "@/lib/holdings-cache";
import { invalidateNetWorth } from "@/lib/networth-cache";
import { amountText } from "@/lib/sip";
import { notify } from "@/lib/notify";
import type { MutualFundItem } from "@/lib/types";

// The NAV field is called "avg_nav" because useNavAutofill fills that field by name.
type FormIn = { date: string; amount: string; avg_nav: string; units: string };
type FormOut = {
  date: string;
  amount: number;
  avg_nav: number;
  units: number | undefined;
};

const API_FIELD: Record<string, keyof FormIn> = {
  date: "date",
  amount: "amount",
  nav: "avg_nav",
  units: "units",
};

function makeSchema(purchaseDate: string | null, lastSale: string | null) {
  return z
    .object({ date: buyDate, amount: buyAmount, avg_nav: buyNav, units: buyUnits })
    .superRefine((v, ctx) => {
      const message = buyDateError(v.date, purchaseDate, lastSale);
      if (message) ctx.addIssue({ code: "custom", path: ["date"], message });
    });
}

function num(text: string | undefined): number | null {
  if (text === undefined || text.trim() === "") return null;
  const n = Number(text);
  return Number.isFinite(n) ? n : null;
}

function BuyForm({
  row,
  onClose,
  onDone,
}: {
  row: MutualFundItem;
  onClose: () => void;
  onDone: (res: BuyResult) => void;
}) {
  const schema = useMemo(
    () => makeSchema(row.purchase_date ?? null, lastSaleDate(row)),
    [row],
  );
  const { control, handleSubmit, setValue, setError } = useForm<FormIn, unknown, FormOut>({
    resolver: zodResolver(schema),
    defaultValues: { date: todayISO(), amount: "", avg_nav: "", units: "" },
  });
  const [saving, setSaving] = useState(false);
  const warning = useDuplicateWarning((m) => duplicateHref("mf", m.id));
  const v = useWatch({ control });

  const navHint = useNavAutofill({
    enabled: true,
    schemeCode: row.scheme_code ?? null,
    purchaseDate: v.date ?? "",
    avgNav: v.avg_nav ?? "",
    setValue,
  });

  const added = previewUnits(num(v.amount), num(v.avg_nav), num(v.units));

  function failed(e: unknown) {
    notify.error(e);
    for (const i of fieldIssues(e)) {
      const name = API_FIELD[i.field];
      if (name) setError(name, { type: "server", message: i.message });
    }
  }

  function succeeded(res: BuyResult) {
    invalidateNetWorth();
    markHoldingsStale("mf");
    notify.success(res);
    onDone(res);
  }

  const onSubmit = handleSubmit(async (values) => {
    const body = buyBody({
      date: values.date,
      amount: values.amount,
      nav: values.avg_nav,
      units: values.units,
    });
    setSaving(true);
    try {
      succeeded(await apiPost<BuyResult>(buyPath(row.id), body));
    } catch (e) {
      const confirmed = async () => {
        try {
          succeeded(await apiPost<BuyResult>(confirmDuplicatePath(buyPath(row.id)), body));
        } catch (err) {
          failed(err);
        }
      };
      if (!warning.intercept(e, confirmed)) failed(e);
    } finally {
      setSaving(false);
    }
  });

  return (
    <FormShell
      onSubmit={onSubmit}
      saving={saving || warning.busy}
      editing={false}
      submitLabel="Buy More"
      savingLabel="Adding…"
      onCancel={onClose}
      duplicate={warning.props}
    >
      <DateField control={control} name="date" label="Date" maxDate={todayISO()} required />
      <TextField
        control={control}
        name="amount"
        label="Amount Invested"
        adornment="₹"
        inputMode="decimal"
        decimals={2}
        required
      />
      <TextField
        control={control}
        name="avg_nav"
        label="NAV Per Unit"
        adornment="₹"
        inputMode="decimal"
        decimals={4}
        hint={navHint}
        required
      />
      <TextField
        control={control}
        name="units"
        label="Units (Optional)"
        inputMode="decimal"
        decimals={3}
        hint={BUY_UNITS_HINT}
      />
      <div
        aria-live="polite"
        className="min-h-9 rounded-lg bg-muted/40 px-3 py-2 text-[13.5px] sm:col-span-2"
      >
        {added !== null ? (
          <p className="num">
            <span>Adds {added.toLocaleString("en-IN", { maximumFractionDigits: 3 })} units</span>
            {num(v.amount) !== null ? (
              <>
                <span className="text-muted-foreground"> · </span>
                <span>{amountText(num(v.amount) ?? 0)} invested</span>
              </>
            ) : null}
          </p>
        ) : (
          <p className="text-muted-foreground">
            Enter the amount and NAV to see the units that will be added.
          </p>
        )}
      </div>
      <p className="text-[13.2px] text-muted-foreground sm:col-span-2">{BUY_INFO_LINE}</p>
    </FormShell>
  );
}

/**
 * Add a purchase to a mutual fund. Open when `row` is set. The NAV is filled in for the date
 * and can be changed; units default to amount ÷ NAV.
 */
export function BuyDialog({
  row,
  name,
  onClose,
  onDone,
}: {
  row: MutualFundItem | null;
  name: string;
  onClose: () => void;
  /** Runs after a successful buy (the dialog should close). */
  onDone?: () => void;
}) {
  // True while the form saves: the dialog can't be dismissed then.
  const [busy, setBusy] = useState(false);
  const finish = onDone ?? onClose;

  return (
    <Dialog
      open={row !== null}
      onOpenChange={(open) => {
        if (open || busy) return;
        onClose();
      }}
    >
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Buy More of {name}</DialogTitle>
          <DialogDescription>
            Record another purchase of this fund.
          </DialogDescription>
        </DialogHeader>
        <FormBusyContext.Provider value={setBusy}>
          {row ? <BuyForm row={row} onClose={onClose} onDone={() => finish()} /> : null}
        </FormBusyContext.Provider>
      </DialogContent>
    </Dialog>
  );
}

"use client";

import { useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { DateField, TextField } from "@/components/forms/fields";
import { FormBusyContext } from "@/components/forms/form-disabled";
import { FormShell } from "@/components/forms/form-shell";
import {
  SELL_DATE_BEFORE_PURCHASE_ERROR,
  SELL_QUANTITY_TOO_MANY_ERROR,
  CHARGES_TOO_HIGH_ERROR,
  destinationChoice,
  exitDate,
  isValidISODate,
  moneyNumber,
  newAccountName,
  saleCharges,
  saleQuantity,
  salePrice,
  todayISO,
} from "@/components/forms/schema";
import { fieldIssues } from "@/components/forms/use-asset-form";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { gainTone } from "@/components/portfolio/grid/gain-cell";
import { apiPost } from "@/lib/api";
import {
  CHOICE_NEW,
  gainText,
  heldText,
  holdingLine,
  landedInAccount,
  priceLabel,
  quantityLabel,
  saleSummary,
  sellDestination,
  sellSubject,
  sellsAll,
  suggestedAccountName,
  wholeQuantity,
  type ExitResult,
  type SellBody,
  type SellSubject,
} from "@/lib/exits";
import { amountText } from "@/lib/sip";
import { notify } from "@/lib/notify";
import type { AssetType, HoldingRow } from "@/lib/types";
import { cn } from "@/lib/utils";
import { afterExit } from "./after-exit";
import { DestinationField } from "./destination-field";
import { ExitSuccess } from "./reinvest";
import { useCashAccounts } from "./use-cash-accounts";
import { usePriceAutofill } from "./use-price-autofill";

type FormIn = {
  date: string;
  quantity: string;
  price: string;
  amount: string;
  charges: string;
  destination: string;
  cash_name: string;
};

type FormOut = {
  date: string;
  quantity: number | undefined;
  price: number | undefined;
  amount: number | undefined;
  charges: number;
  destination: string;
  cash_name: string;
};

const FIELDS = ["date", "quantity", "price", "amount", "charges", "cash_name"] as const;

function round2(n: number): number {
  return Math.round((n + Number.EPSILON) * 100) / 100;
}

function makeSchema(subject: SellSubject) {
  const other = subject.type === "other";
  const unused = z.string().transform((): number | undefined => undefined);
  const quantity: z.ZodType<number | undefined, string> = other
    ? unused
    : saleQuantity(wholeQuantity(subject.type));
  const price: z.ZodType<number | undefined, string> = other ? unused : salePrice;
  const amount: z.ZodType<number | undefined, string> = other ? moneyNumber : unused;
  return z
    .object({
      date: exitDate,
      quantity,
      price,
      amount,
      charges: saleCharges,
      destination: destinationChoice,
      cash_name: z.string(),
    })
    .superRefine((v, ctx) => {
      if (
        v.quantity !== undefined &&
        subject.held !== null &&
        v.quantity > subject.held + 0.00005
      ) {
        ctx.addIssue({
          code: "custom",
          path: ["quantity"],
          message: SELL_QUANTITY_TOO_MANY_ERROR,
        });
      }
      if (subject.startDate && isValidISODate(v.date) && v.date < subject.startDate) {
        ctx.addIssue({
          code: "custom",
          path: ["date"],
          message: SELL_DATE_BEFORE_PURCHASE_ERROR,
        });
      }
      const gross =
        v.amount !== undefined
          ? v.amount
          : v.quantity !== undefined && v.price !== undefined
            ? round2(v.quantity * v.price)
            : undefined;
      if (gross !== undefined && v.charges >= gross) {
        ctx.addIssue({
          code: "custom",
          path: ["charges"],
          message: CHARGES_TOO_HIGH_ERROR,
        });
      }
      if (v.destination === CHOICE_NEW) {
        const r = newAccountName.safeParse(v.cash_name);
        if (!r.success) {
          ctx.addIssue({
            code: "custom",
            path: ["cash_name"],
            message: r.error.issues[0]?.message ?? "Required",
          });
        }
      }
    });
}

function num(text: string | undefined): number | null {
  if (text === undefined || text.trim() === "") return null;
  const n = Number(text);
  return Number.isFinite(n) ? n : null;
}

function SellForm({
  type,
  subject,
  onClose,
  onSold,
}: {
  type: AssetType;
  subject: SellSubject;
  onClose: () => void;
  onSold: (res: ExitResult) => void;
}) {
  const schema = useMemo(() => makeSchema(subject), [subject]);
  const { control, handleSubmit, setValue, setError } = useForm<FormIn, unknown, FormOut>({
    resolver: zodResolver(schema),
    defaultValues: {
      date: todayISO(),
      quantity: "",
      price: "",
      amount: "",
      charges: "",
      destination: "",
      cash_name: "",
    },
  });
  const [saving, setSaving] = useState(false);
  const { accounts, error: accountsError } = useCashAccounts();
  const v = useWatch({ control });
  const other = subject.type === "other";

  const hint = usePriceAutofill({
    source: other ? null : subject.source,
    date: v.date ?? "",
    price: v.price ?? "",
    setValue,
  });

  const quantity = num(v.quantity);
  const summary = saleSummary({
    type: subject.type,
    held: subject.held,
    invested: subject.invested,
    quantity,
    price: num(v.price),
    amount: num(v.amount),
    charges: num(v.charges) ?? 0,
  });
  const all = sellsAll(subject.held, quantity);
  const held = summary && isValidISODate(v.date ?? "") ? heldText(subject.startDate, v.date ?? "") : null;
  const gain = summary ? gainText(summary) : null;

  const onSubmit = handleSubmit(async (values) => {
    const destination = sellDestination(values.destination, values.cash_name);
    if (!destination) return;
    const body: SellBody = {
      date: values.date,
      charges: values.charges,
      destination,
      ...(other
        ? { amount: values.amount }
        : { quantity: values.quantity, price: values.price }),
    };
    setSaving(true);
    try {
      const res = await apiPost<ExitResult>(
        `/holdings/${type}/${subject.id}/sell`,
        body,
      );
      notify.success(res);
      onSold(res);
    } catch (e) {
      notify.error(e);
      for (const i of fieldIssues(e)) {
        const field = i.field === "cash_id" || i.field === "kind" ? "destination" : i.field;
        const name = [...FIELDS, "destination" as const].find((f) => f === field);
        if (name) setError(name, { type: "server", message: i.message });
      }
    } finally {
      setSaving(false);
    }
  });

  return (
    <FormShell
      onSubmit={onSubmit}
      saving={saving}
      editing={false}
      submitLabel="Sell"
      savingLabel="Selling…"
      onCancel={onClose}
    >
      <DateField
        control={control}
        name="date"
        label="Date"
        maxDate={todayISO()}
        required
      />
      {other ? (
        <TextField
          control={control}
          name="amount"
          label="Sale amount"
          adornment="₹"
          inputMode="decimal"
          decimals={2}
          required
        />
      ) : (
        <div className="flex flex-col gap-1.5">
          <TextField
            control={control}
            name="quantity"
            label={quantityLabel(subject.type)}
            inputMode={wholeQuantity(subject.type) ? "numeric" : "decimal"}
            decimals={wholeQuantity(subject.type) ? 0 : 3}
            required
          />
          <button
            type="button"
            aria-pressed={all}
            disabled={saving}
            onClick={() =>
              setValue("quantity", all ? "" : String(subject.held), {
                shouldDirty: true,
                shouldValidate: true,
              })
            }
            className={cn(
              "w-fit text-xs underline-offset-2 hover:underline disabled:opacity-50",
              all
                ? "font-medium text-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {all ? "Selling All · Clear" : "Sell All"}
          </button>
        </div>
      )}
      {other ? null : (
        <TextField
          control={control}
          name="price"
          label={priceLabel(subject.type)}
          adornment="₹"
          inputMode="decimal"
          decimals={4}
          hint={hint}
          required
        />
      )}
      <TextField
        control={control}
        name="charges"
        label="Charges"
        adornment="₹"
        inputMode="decimal"
        decimals={2}
        hint="Brokerage, taxes or fees paid on the sale"
      />
      <div
        aria-live="polite"
        className="min-h-9 rounded-lg bg-muted/40 px-3 py-2 text-[13.5px] sm:col-span-2"
      >
        {summary ? (
          <>
            <p className="num">
              <span>You get {amountText(summary.youGet)}</span>
              {summary.hasCost ? (
                <>
                  <span className="text-muted-foreground"> · </span>
                  <span>Cost {amountText(summary.cost)}</span>
                </>
              ) : null}
              {gain ? (
                <>
                  <span className="text-muted-foreground"> · </span>
                  <span className={gainTone(summary.gain)}>{gain}</span>
                </>
              ) : null}
              {held ? (
                <span className="text-muted-foreground"> ({held})</span>
              ) : null}
            </p>
            {summary.estimated ? (
              <p className="text-[13.2px] text-muted-foreground">
                Cost is an estimate. The oldest units are sold first.
              </p>
            ) : null}
          </>
        ) : (
          <p className="text-muted-foreground">
            Enter the date, {other ? "amount" : "quantity and price"} to see what you get.
          </p>
        )}
      </div>
      {subject.hasSip && all ? (
        <p className="text-[13.2px] text-muted-foreground sm:col-span-2">
          This also cancels its SIP.
        </p>
      ) : null}
      <DestinationField
        control={control}
        setValue={setValue}
        accounts={accounts}
        accountsError={accountsError}
        amount={summary?.youGet ?? null}
        suggestedName={suggestedAccountName(subject.suggestedBank)}
      />
    </FormShell>
  );
}

/**
 * Sell all or part of a holding. Open when `row` is set. The sale price is filled in for the
 * date (stock close, fund NAV, metal rate) and can be changed.
 */
export function SellDialog({
  type,
  row,
  name,
  onClose,
  onDone,
}: {
  type: AssetType;
  row: HoldingRow | null;
  name: string;
  onClose: () => void;
  /** Runs after a successful sale (the dialog should close). */
  onDone?: () => void;
}) {
  const subject = useMemo(
    () => (row ? sellSubject(type, row, name) : null),
    [type, row, name],
  );
  // True while the form saves: the dialog can't be dismissed then.
  const [busy, setBusy] = useState(false);
  const [success, setSuccess] = useState<ExitResult | null>(null);
  const finish = onDone ?? onClose;

  // Lists reload only when the success step is left, so the dialog's holding stays in place.
  function done(res: ExitResult) {
    afterExit(type, res);
    setSuccess(null);
    finish();
  }

  return (
    <Dialog
      open={subject !== null || success !== null}
      onOpenChange={(open) => {
        if (open || busy) return;
        if (success) done(success);
        else onClose();
      }}
    >
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Sell {name}</DialogTitle>
          <DialogDescription>{subject ? holdingLine(subject) : ""}</DialogDescription>
        </DialogHeader>
        <FormBusyContext.Provider value={setBusy}>
          {success ? (
            <ExitSuccess
              exit={success}
              cashName={success.cash_name ?? "your account"}
              onDone={() => done(success)}
            />
          ) : subject ? (
            <SellForm
              type={type}
              subject={subject}
              onClose={onClose}
              onSold={(res) => {
                if (landedInAccount(res)) setSuccess(res);
                else done(res);
              }}
            />
          ) : null}
        </FormBusyContext.Provider>
      </DialogContent>
    </Dialog>
  );
}

"use client";

import { useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { DateField, TextField } from "@/components/forms/fields";
import { FormBusyContext, FormDisabledContext, useReportBusy } from "@/components/forms/form-disabled";
import {
  SETTLE_DATE_BEFORE_MATURITY_ERROR,
  destinationChoice,
  exitDate,
  isValidISODate,
  moneyNumber,
  newAccountName,
  todayISO,
} from "@/components/forms/schema";
import { fieldIssues } from "@/components/forms/use-asset-form";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiPost } from "@/lib/api";
import {
  CHOICE_NEW,
  landedInAccount,
  settleDestination,
  settleSubject,
  suggestedAccountName,
  type ExitResult,
  type SettleBody,
  type SettleSubject,
} from "@/lib/exits";
import { formatDate } from "@/lib/format";
import { notify } from "@/lib/notify";
import type { AssetType, HoldingRow } from "@/lib/types";
import { afterExit } from "./after-exit";
import { DestinationField } from "./destination-field";
import { ExitSuccess } from "./reinvest";
import { useCashAccounts } from "./use-cash-accounts";

type FormIn = {
  amount: string;
  date: string;
  destination: string;
  cash_name: string;
};

type FormOut = {
  amount: number;
  date: string;
  destination: string;
  cash_name: string;
};

const FIELDS = ["amount", "date", "cash_name"] as const;

function makeSchema(subject: SettleSubject) {
  return z
    .object({
      amount: moneyNumber,
      date: exitDate,
      destination: destinationChoice,
      cash_name: z.string(),
    })
    .superRefine((v, ctx) => {
      if (isValidISODate(v.date) && v.date < subject.maturityDate) {
        ctx.addIssue({
          code: "custom",
          path: ["date"],
          message: SETTLE_DATE_BEFORE_MATURITY_ERROR,
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

function SettleForm({
  type,
  subject,
  onClose,
  onSettled,
}: {
  type: AssetType;
  subject: SettleSubject;
  onClose: () => void;
  onSettled: (res: ExitResult) => void;
}) {
  const schema = useMemo(() => makeSchema(subject), [subject]);
  const { control, handleSubmit, setValue, setError } = useForm<FormIn, unknown, FormOut>({
    resolver: zodResolver(schema),
    defaultValues: {
      amount: subject.maturityAmount !== null ? String(subject.maturityAmount) : "",
      date: subject.maturityDate,
      destination: "",
      cash_name: "",
    },
  });
  const [saving, setSaving] = useState(false);
  useReportBusy(saving);
  const { accounts, error: accountsError } = useCashAccounts();
  const v = useWatch({ control });
  const amount = Number(v.amount);

  const submit = handleSubmit(async (values) => {
    const destination = settleDestination(values.destination, values.cash_name);
    if (!destination) return;
    const body: SettleBody = {
      date: values.date,
      amount: values.amount,
      destination,
    };
    setSaving(true);
    try {
      const res = await apiPost<ExitResult>(
        `/holdings/${type}/${subject.id}/settle`,
        body,
      );
      notify.success(res);
      onSettled(res);
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
    <div className="flex flex-col gap-5">
      <FormDisabledContext.Provider value={saving}>
        <div
          className="grid gap-x-6 gap-y-3 sm:grid-cols-2"
          onKeyDown={(e) => {
            if (e.key !== "Enter" || !(e.target instanceof HTMLInputElement)) return;
            e.preventDefault();
            void submit();
          }}
        >
          <TextField
            control={control}
            name="amount"
            label="Amount received"
            adornment="₹"
            inputMode="decimal"
            decimals={2}
            hint={
              subject.maturityAmount !== null
                ? "Estimated from the rate. Change it if you received a different amount."
                : null
            }
            required
          />
          <DateField
            control={control}
            name="date"
            label="Date received"
            maxDate={todayISO()}
            required
          />
          <DestinationField
            control={control}
            setValue={setValue}
            accounts={accounts}
            accountsError={accountsError}
            amount={Number.isFinite(amount) && amount > 0 ? amount : null}
            suggestedName={suggestedAccountName(subject.suggestedBank)}
          />
        </div>
      </FormDisabledContext.Provider>
      <div className="flex items-center justify-end gap-2 pt-2">
        <Button type="button" variant="ghost" onClick={onClose} disabled={saving}>
          Cancel
        </Button>
        <Button type="button" disabled={saving} onClick={() => void submit()}>
          {saving ? <Loader2 className="size-3.5 animate-spin" /> : null}
          {saving ? "Settling…" : "Settle"}
        </Button>
      </div>
    </div>
  );
}

/**
 * Record where the money of a matured deposit or bond landed. Open when `row` is set. When the
 * money went into a cash account the dialog stays open on a step offering to reinvest it.
 */
export function SettleDialog({
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
  /** Runs after a successful settlement (the dialog should close). */
  onDone?: () => void;
}) {
  const subject = useMemo(
    () => (row ? settleSubject(type, row, name) : null),
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
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Settle {name}</DialogTitle>
          <DialogDescription>
            {subject ? `Matured on ${formatDate(subject.maturityDate)}` : ""}
          </DialogDescription>
        </DialogHeader>
        <FormBusyContext.Provider value={setBusy}>
          {success ? (
            <ExitSuccess
              exit={success}
              cashName={success.cash_name ?? "your account"}
              onDone={() => done(success)}
            />
          ) : subject ? (
            <SettleForm
              type={type}
              subject={subject}
              onClose={onClose}
              onSettled={(res) => {
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

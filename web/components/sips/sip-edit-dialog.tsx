"use client";

import { useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { DayOfMonthField } from "@/components/forms/day-of-month-field";
import { DateField, TextField } from "@/components/forms/fields";
import { FormBusyContext } from "@/components/forms/form-disabled";
import { FormShell } from "@/components/forms/form-shell";
import {
  SIP_END_BEFORE_START_ERROR,
  optionalSipEndDate,
  sipAmount,
  sipDay,
  sipEndAfterStart,
} from "@/components/forms/schema";
import { fieldIssues } from "@/components/forms/use-asset-form";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiPut } from "@/lib/api";
import { markHoldingsStale } from "@/lib/holdings-cache";
import { notify } from "@/lib/notify";
import { scheduleText } from "@/lib/sip";
import type { Sip, SipResult, SipUpdateInput } from "@/lib/types";

const FIELDS = ["amount", "day_of_month", "end_date"] as const;

function makeSchema(startDate: string) {
  return z
    .object({
      amount: sipAmount,
      day_of_month: sipDay,
      end_date: optionalSipEndDate,
    })
    .superRefine((v, ctx) => {
      if (!sipEndAfterStart(startDate, v.end_date)) {
        ctx.addIssue({
          code: "custom",
          path: ["end_date"],
          message: SIP_END_BEFORE_START_ERROR,
        });
      }
    });
}

type FormIn = { amount: string; day_of_month: string; end_date: string };
type FormOut = {
  amount: number;
  day_of_month: number;
  end_date: string | null;
};

function EditForm({
  sip,
  onSaved,
  onCancel,
}: {
  sip: Sip;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const schema = useMemo(() => makeSchema(sip.start_date), [sip.start_date]);
  const { control, handleSubmit, setValue, setError } = useForm<
    FormIn,
    unknown,
    FormOut
  >({
    resolver: zodResolver(schema),
    defaultValues: {
      amount: String(sip.amount),
      day_of_month: String(sip.day_of_month),
      end_date: sip.end_date ?? "",
    },
  });
  const [saving, setSaving] = useState(false);
  const endDate = useWatch({ control, name: "end_date" });

  const onSubmit = handleSubmit(async (values) => {
    const payload: SipUpdateInput = {
      amount: values.amount,
      day_of_month: values.day_of_month,
      end_date: values.end_date,
    };
    setSaving(true);
    try {
      const saved = await apiPut<SipResult>(`/sips/${sip.id}`, payload);
      markHoldingsStale("mf");
      notify.success(saved);
      onSaved();
    } catch (e) {
      notify.error(e);
      for (const i of fieldIssues(e)) {
        const name = FIELDS.find((f) => f === i.field);
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
      editing
      onCancel={onCancel}
    >
      <TextField
        control={control}
        name="amount"
        label="Monthly amount"
        adornment="₹"
        inputMode="decimal"
        decimals={2}
        required
      />
      <DayOfMonthField
        control={control}
        name="day_of_month"
        label="SIP date"
        required
      />
      <div className="flex flex-col gap-1.5">
        <DateField control={control} name="end_date" label="End date" />
        {endDate ? (
          <button
            type="button"
            disabled={saving}
            onClick={() => setValue("end_date", "", { shouldDirty: true })}
            className="w-fit text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline disabled:opacity-50"
          >
            Remove end date
          </button>
        ) : (
          <p className="text-[11px] text-muted-foreground">
            Leave empty to keep the SIP running until you cancel it.
          </p>
        )}
      </div>
      <p className="self-end text-[11px] text-muted-foreground sm:col-span-2">
        Changes apply to future instalments only. Instalments already added
        stay as they are.
      </p>
    </FormShell>
  );
}

/** Dialog to change a SIP's amount, day of month and end date. */
export function SipEditDialog({
  sip,
  open,
  onClose,
  onSaved,
}: {
  sip: Sip;
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  // True while the form saves: the dialog can't be dismissed then.
  const [busy, setBusy] = useState(false);
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !busy) onClose();
      }}
    >
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Update SIP</DialogTitle>
          <DialogDescription>
            {sip.fund_name} · {scheduleText(sip)}
          </DialogDescription>
        </DialogHeader>
        <FormBusyContext.Provider value={setBusy}>
          {open ? (
            <EditForm sip={sip} onSaved={onSaved} onCancel={onClose} />
          ) : null}
        </FormBusyContext.Provider>
      </DialogContent>
    </Dialog>
  );
}

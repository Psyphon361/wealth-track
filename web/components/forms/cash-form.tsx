"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  CASH_KIND_LABELS,
  type Cash,
  type CashInput,
  type CashKind,
} from "@/lib/types";
import { FormShell } from "./form-shell";
import {
  DateField,
  NotesField,
  SelectField,
  TextField,
  toOptions,
} from "./fields";
import {
  cashKindEnum,
  FD_RATE_ERROR,
  maxFutureDateISO,
  moneyNumber,
  notesText,
  optionalRate,
  requiredText,
  startDateString,
  todayISO,
} from "./schema";
import { useAssetSave } from "./use-asset-form";
import { usePaidFrom } from "./paid-from-field";
import type { ReinvestPrefill } from "@/lib/reinvest";

const schema = z.object({
  name: requiredText,
  kind: cashKindEnum,
  balance: moneyNumber,
  balance_date: startDateString,
  interest_rate: optionalRate(15, FD_RATE_ERROR),
  notes: notesText,
});

type FormIn = z.input<typeof schema>;
type FormOut = z.output<typeof schema>;

const KIND_OPTIONS = toOptions(CASH_KIND_LABELS);

function toDefaults(r?: Cash): FormIn {
  return {
    name: r?.name ?? "",
    // Blank until chosen; the schema then reports "Choose an account type".
    kind: r?.kind ?? ("" as CashKind),
    balance: r ? String(r.balance) : "",
    balance_date: r?.balance_date ?? todayISO(),
    interest_rate:
      r?.interest_rate == null ? "" : String(r.interest_rate),
    notes: r?.notes ?? "",
  };
}

export function CashForm({
  record,
  onSaved,
  onCancel,
  reinvest,
}: {
  /** One-shot prefill from "Reinvest" (create only). */
  reinvest?: ReinvestPrefill | null;
  record?: Cash;
  onSaved?: (record: Cash) => void;
  onCancel?: () => void;
}) {
  const { control, handleSubmit, setValue } = useForm<FormIn, unknown, FormOut>({
    resolver: zodResolver(schema),
    defaultValues: toDefaults(record),
  });
  const pf = usePaidFrom({ type: "cash", record, control, setValue, reinvest });
  const { saving, save, duplicate } = useAssetSave("cash", record, onSaved, pf.applyIssues);

  const onSubmit = handleSubmit((values) => {
    if (pf.error) return;
    const payload: CashInput = {
      name: values.name,
      kind: values.kind,
      balance: values.balance,
      interest_rate: values.interest_rate,
      balance_date: values.balance_date,
      notes: values.notes,
    };
    return save({ ...payload, ...pf.body });
  });

  return (
    <FormShell
      onSubmit={onSubmit}
      saving={saving}
      editing={!!record}
      duplicate={duplicate}
      paidFrom={pf}
      onCancel={onCancel}
    >
      <TextField
        control={control}
        name="name"
        label="Name"
        placeholder="e.g. HDFC savings"
        required
      />
      <SelectField
        control={control}
        name="kind"
        label="Account type"
        options={KIND_OPTIONS}
        required
      />
      <TextField
        control={control}
        name="balance"
        label="Balance"
        adornment="₹"
        inputMode="decimal"
        decimals={2}
        required
      />
      <DateField
        control={control}
        name="balance_date"
        label="Balance as of"
        maxDate={maxFutureDateISO()}
        required
      />
      <TextField
        control={control}
        name="interest_rate"
        label="Interest rate p.a."
        adornment="%"
        inputMode="decimal"
        decimals={2}
      />
      <div className="sm:col-span-2">
        <NotesField control={control} name="notes" />
      </div>
    </FormShell>
  );
}

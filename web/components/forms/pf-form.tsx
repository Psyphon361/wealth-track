"use client";

import { useEffect } from "react";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  PF_KIND_LABELS,
  type Pf,
  type PfInput,
  type PfKind,
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
  dateString,
  FD_RATE_ERROR,
  maxFutureDateISO,
  moneyNumber,
  notesText,
  optionalMoney,
  PF_OPENED_ON_ERROR,
  pfKindEnum,
  rateNumber,
  requiredText,
  startDateString,
  todayISO,
} from "./schema";
import { useAssetSave } from "./use-asset-form";
import { usePaidFrom } from "./paid-from-field";
import type { ReinvestPrefill } from "@/lib/reinvest";

const schema = z
  .object({
    name: requiredText,
    kind: pfKindEnum,
    balance: moneyNumber,
    balance_date: startDateString,
    interest_rate: rateNumber(15, FD_RATE_ERROR),
    contributed: optionalMoney,
    opened_on: z.string(),
    notes: notesText,
  })
  .superRefine((v, ctx) => {
    if (v.kind !== "ppf") return;
    if (v.opened_on === "") {
      ctx.addIssue({
        code: "custom",
        path: ["opened_on"],
        message: PF_OPENED_ON_ERROR,
      });
      return;
    }
    const r = dateString.safeParse(v.opened_on);
    if (!r.success) {
      for (const i of r.error.issues) {
        ctx.addIssue({ code: "custom", path: ["opened_on"], message: i.message });
      }
    }
  });

type FormIn = z.input<typeof schema>;
type FormOut = z.output<typeof schema>;

const KIND_OPTIONS = toOptions(PF_KIND_LABELS);

/** Default interest rate (% p.a.) suggested per account type. */
const DEFAULT_RATE: Record<PfKind, string> = {
  epf: "8.25",
  vpf: "8.25",
  ppf: "7.1",
};

function toDefaults(r?: Pf): FormIn {
  return {
    name: r?.name ?? "",
    // Blank until chosen; the schema then reports "Choose an account type".
    kind: r?.kind ?? ("" as PfKind),
    balance: r ? String(r.balance) : "",
    balance_date: r?.balance_date ?? todayISO(),
    interest_rate: r ? String(r.interest_rate) : "",
    contributed: r?.contributed == null ? "" : String(r.contributed),
    opened_on: r?.opened_on ?? "",
    notes: r?.notes ?? "",
  };
}

export function PfForm({
  record,
  onSaved,
  onCancel,
  reinvest,
}: {
  /** One-shot prefill from "Reinvest" (create only). */
  reinvest?: ReinvestPrefill | null;
  record?: Pf;
  onSaved?: (record: Pf) => void;
  onCancel?: () => void;
}) {
  const {
    control,
    handleSubmit,
    setValue,
    formState: { dirtyFields },
  } = useForm<FormIn, unknown, FormOut>({
    resolver: zodResolver(schema),
    defaultValues: toDefaults(record),
  });
  const kind = useWatch({ control, name: "kind" });
  const rateEdited = !!dirtyFields.interest_rate;
  const pf = usePaidFrom({ type: "pf", record, control, setValue, reinvest });
  const { saving, save, duplicate } = useAssetSave("pf", record, onSaved, pf.applyIssues);

  // Suggest a rate for the chosen account type until the user edits it.
  useEffect(() => {
    if (record || rateEdited) return;
    if (kind === "epf" || kind === "vpf" || kind === "ppf") {
      setValue("interest_rate", DEFAULT_RATE[kind]);
    }
  }, [kind, record, rateEdited, setValue]);

  const onSubmit = handleSubmit((values) => {
    if (pf.error) return;
    const payload: PfInput = {
      name: values.name,
      kind: values.kind,
      balance: values.balance,
      balance_date: values.balance_date,
      interest_rate: values.interest_rate,
      contributed: values.contributed,
      opened_on: values.kind === "ppf" ? values.opened_on : null,
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
        placeholder="e.g. EPF – Acme Corp"
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
        label="Current balance"
        adornment="₹"
        inputMode="decimal"
        decimals={2}
        hint="Passbook total, including interest"
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
        label="Interest rate (%)"
        adornment="%"
        inputMode="decimal"
        decimals={2}
        required
      />
      <TextField
        control={control}
        name="contributed"
        label="Total deposited"
        adornment="₹"
        inputMode="decimal"
        decimals={2}
        hint="Excluding interest. EPF: employee + employer share (not EPS)"
      />
      {kind === "ppf" ? (
        <DateField
          control={control}
          name="opened_on"
          label="Opening date"
          maxDate={maxFutureDateISO()}
          required
        />
      ) : null}
      <div className="sm:col-span-2">
        <NotesField control={control} name="notes" />
      </div>
    </FormShell>
  );
}

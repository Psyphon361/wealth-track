"use client";

import { useEffect } from "react";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  COMPOUNDING_LABELS,
  PAYOUT_TYPE_LABELS,
  type FixedDeposit,
  type FixedDepositInput,
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
  FD_RATE_ERROR,
  FD_TENURE_ERROR,
  PAYOUT_FREQUENCY_ERROR,
  TENURE_ERROR,
  compoundingEnum,
  maxFutureDateISO,
  moneyNumber,
  notesText,
  optionalText,
  payoutEnum,
  rateNumber,
  requiredText,
  startDateString,
  tenureIsPositive,
  tenureOk,
  tenurePart,
} from "./schema";
import { TenurePicker } from "./tenure-picker";
import { useAssetSave } from "./use-asset-form";

const schema = z
  .object({
    bank: requiredText,
    label: optionalText,
    principal: moneyNumber,
    rate: rateNumber(15, FD_RATE_ERROR),
    start_date: startDateString,
    tenure_years: tenurePart,
    tenure_months: tenurePart,
    tenure_days: tenurePart,
    compounding: compoundingEnum,
    payout_type: payoutEnum,
    notes: notesText,
  })
  .refine(tenureIsPositive, {
    message: TENURE_ERROR,
    path: ["tenure_years"],
  })
  .refine((v) => tenureOk("fd", v), {
    message: FD_TENURE_ERROR,
    path: ["tenure_years"],
  })
  .refine((v) => !(v.payout_type === "payout" && v.compounding === "simple"), {
    message: PAYOUT_FREQUENCY_ERROR,
    path: ["compounding"],
  });

type FormIn = z.input<typeof schema>;
type FormOut = z.output<typeof schema>;

const COMPOUNDING_OPTIONS = toOptions(COMPOUNDING_LABELS);
const FREQUENCY_OPTIONS = COMPOUNDING_OPTIONS.filter(
  (o) => o.value !== "simple",
);
const PAYOUT_OPTIONS = toOptions(PAYOUT_TYPE_LABELS);

function toDefaults(r?: FixedDeposit): FormIn {
  return {
    bank: r?.bank ?? "",
    label: r?.label ?? "",
    principal: r ? String(r.principal) : "",
    rate: r ? String(r.rate) : "",
    start_date: r?.start_date ?? "",
    tenure_years: String(r?.tenure_years ?? 0),
    tenure_months: String(r?.tenure_months ?? 0),
    tenure_days: String(r?.tenure_days ?? 0),
    compounding: r?.compounding ?? "quarterly",
    payout_type: r?.payout_type ?? "cumulative",
    notes: r?.notes ?? "",
  };
}

export function FdForm({
  record,
  onSaved,
  onCancel,
}: {
  record?: FixedDeposit;
  onSaved?: (record: FixedDeposit) => void;
  onCancel?: () => void;
}) {
  const { saving, save } = useAssetSave("fd", record, onSaved);
  const { control, handleSubmit, setValue, getValues } = useForm<FormIn, unknown, FormOut>({
    resolver: zodResolver(schema),
    defaultValues: toDefaults(record),
  });
  const payoutType = useWatch({ control, name: "payout_type" });
  const isPayout = payoutType === "payout";
  useEffect(() => {
    if (isPayout && getValues("compounding") === "simple") {
      setValue("compounding", "quarterly");
    }
  }, [isPayout, getValues, setValue]);
  const onSubmit = handleSubmit((values) => {
    const payload: FixedDepositInput = values;
    return save(payload);
  });

  return (
    <FormShell
      onSubmit={onSubmit}
      saving={saving}
      editing={!!record}
      onCancel={onCancel}
    >
      <TextField control={control} name="bank" label="Bank" required />
      <TextField control={control} name="label" label="Label" />
      <TextField
        control={control}
        name="principal"
        label="Principal"
        adornment="₹"
        inputMode="decimal"
        decimals={2}
        required
      />
      <TextField
        control={control}
        name="rate"
        label="Interest rate p.a."
        adornment="%"
        inputMode="decimal"
        decimals={2}
        required
      />
      <DateField
        control={control}
        name="start_date"
        label="Start date"
        maxDate={maxFutureDateISO()}
        required
      />
      <SelectField
        control={control}
        name="compounding"
        label={isPayout ? "Payout frequency" : "Compounding"}
        options={isPayout ? FREQUENCY_OPTIONS : COMPOUNDING_OPTIONS}
        required
      />
      <SelectField
        control={control}
        name="payout_type"
        label="Payout type"
        options={PAYOUT_OPTIONS}
        required
      />
      <div className="sm:col-span-2">
        <TenurePicker
          control={control}
          names={{
            years: "tenure_years",
            months: "tenure_months",
            days: "tenure_days",
          }}
        />
      </div>
      <div className="sm:col-span-2">
        <NotesField control={control} name="notes" />
      </div>
    </FormShell>
  );
}

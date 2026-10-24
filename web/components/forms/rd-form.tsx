"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  COMPOUNDING_LABELS,
  type RecurringDeposit,
  type RecurringDepositInput,
} from "@/lib/types";
import { FormShell } from "./form-shell";
import { NotesField, SelectField, TextField, toOptions } from "./fields";
import {
  TENURE_ERROR,
  compoundingEnum,
  dateString,
  optionalText,
  positiveNumber,
  requiredText,
  tenureIsPositive,
  tenurePart,
} from "./schema";
import { TenurePicker } from "./tenure-picker";
import { useAssetSave } from "./use-asset-form";

const schema = z
  .object({
    bank: requiredText,
    label: optionalText,
    monthly_instalment: positiveNumber,
    rate: positiveNumber,
    start_date: dateString,
    tenure_years: tenurePart,
    tenure_months: tenurePart,
    tenure_days: tenurePart,
    compounding: compoundingEnum,
    notes: optionalText,
  })
  .refine(tenureIsPositive, {
    message: TENURE_ERROR,
    path: ["tenure_years"],
  });

type FormIn = z.input<typeof schema>;
type FormOut = z.output<typeof schema>;

const COMPOUNDING_OPTIONS = toOptions(COMPOUNDING_LABELS);

function toDefaults(r?: RecurringDeposit): FormIn {
  return {
    bank: r?.bank ?? "",
    label: r?.label ?? "",
    monthly_instalment: r ? String(r.monthly_instalment) : "",
    rate: r ? String(r.rate) : "",
    start_date: r?.start_date ?? "",
    tenure_years: String(r?.tenure_years ?? 0),
    tenure_months: String(r?.tenure_months ?? 0),
    tenure_days: String(r?.tenure_days ?? 0),
    compounding: r?.compounding ?? "quarterly",
    notes: r?.notes ?? "",
  };
}

export function RdForm({
  record,
  onSaved,
  onCancel,
}: {
  record?: RecurringDeposit;
  onSaved?: (record: RecurringDeposit) => void;
  onCancel?: () => void;
}) {
  const { saving, save } = useAssetSave("rd", record, onSaved);
  const { control, handleSubmit } = useForm<FormIn, unknown, FormOut>({
    resolver: zodResolver(schema),
    defaultValues: toDefaults(record),
  });
  const onSubmit = handleSubmit((values) => {
    const payload: RecurringDepositInput = values;
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
        name="monthly_instalment"
        label="Monthly instalment"
        adornment="₹"
        inputMode="decimal"
        required
      />
      <TextField
        control={control}
        name="rate"
        label="Interest rate p.a."
        adornment="%"
        inputMode="decimal"
        required
      />
      <TextField
        control={control}
        name="start_date"
        label="Start date"
        type="date"
        required
      />
      <SelectField
        control={control}
        name="compounding"
        label="Compounding"
        options={COMPOUNDING_OPTIONS}
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

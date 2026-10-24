"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  MF_CATEGORY_LABELS,
  type MutualFund,
  type MutualFundInput,
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
  mfCategoryEnum,
  optionalText,
  positiveNumber,
  positiveUnits,
  requiredText,
} from "./schema";
import { useAssetSave } from "./use-asset-form";

const schema = z.object({
  scheme_name: requiredText,
  platform: optionalText,
  category: mfCategoryEnum,
  units: positiveUnits,
  avg_nav: positiveNumber,
  purchase_date: dateString,
  notes: optionalText,
});

type FormIn = z.input<typeof schema>;
type FormOut = z.output<typeof schema>;

const CATEGORY_OPTIONS = toOptions(MF_CATEGORY_LABELS);

function toDefaults(r?: MutualFund): FormIn {
  return {
    scheme_name: r?.scheme_name ?? "",
    platform: r?.platform ?? "",
    category: r?.category ?? "equity",
    units: r ? String(r.units) : "",
    avg_nav: r ? String(r.avg_nav) : "",
    purchase_date: r?.purchase_date ?? "",
    notes: r?.notes ?? "",
  };
}

export function MfForm({
  record,
  onSaved,
  onCancel,
}: {
  record?: MutualFund;
  onSaved?: (record: MutualFund) => void;
  onCancel?: () => void;
}) {
  const { saving, save } = useAssetSave("mf", record, onSaved);
  const { control, handleSubmit } = useForm<FormIn, unknown, FormOut>({
    resolver: zodResolver(schema),
    defaultValues: toDefaults(record),
  });
  const onSubmit = handleSubmit((values) => {
    const payload: MutualFundInput = values;
    return save(payload);
  });

  return (
    <FormShell
      onSubmit={onSubmit}
      saving={saving}
      editing={!!record}
      onCancel={onCancel}
    >
      <TextField
        control={control}
        name="scheme_name"
        label="Scheme name"
        required
      />
      <TextField control={control} name="platform" label="Platform" />
      <SelectField
        control={control}
        name="category"
        label="Category"
        options={CATEGORY_OPTIONS}
        required
      />
      <TextField
        control={control}
        name="units"
        label="Units"
        inputMode="decimal"
        required
      />
      <TextField
        control={control}
        name="avg_nav"
        label="Average NAV"
        adornment="₹"
        inputMode="decimal"
        required
      />
      <DateField
        control={control}
        name="purchase_date"
        label="Purchase date"
        required
      />
      <div className="sm:col-span-2">
        <NotesField control={control} name="notes" />
      </div>
    </FormShell>
  );
}

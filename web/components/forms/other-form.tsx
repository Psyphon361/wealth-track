"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import type { Other, OtherInput } from "@/lib/types";
import { FormShell } from "./form-shell";
import { CategoryField } from "./category-field";
import { DateField, NotesField, TextField } from "./fields";
import {
  categoryText,
  dateString,
  maxFutureDateISO,
  moneyNumber,
  notesText,
  optionalMoney,
  OTHER_ACQUIRED_AFTER_VALUE_ERROR,
  requiredText,
  startDateString,
  todayISO,
} from "./schema";
import { useAssetSave } from "./use-asset-form";

const schema = z
  .object({
    name: requiredText,
    category: categoryText,
    current_value: moneyNumber,
    value_date: startDateString,
    invested_amount: optionalMoney,
    acquired_on: z.string(),
    notes: notesText,
  })
  .superRefine((v, ctx) => {
    if (v.acquired_on === "") return;
    const r = startDateString.safeParse(v.acquired_on);
    if (!r.success) {
      for (const i of r.error.issues) {
        ctx.addIssue({ code: "custom", path: ["acquired_on"], message: i.message });
      }
      return;
    }
    if (
      dateString.safeParse(v.value_date).success &&
      v.acquired_on > v.value_date
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["acquired_on"],
        message: OTHER_ACQUIRED_AFTER_VALUE_ERROR,
      });
    }
  });

type FormIn = z.input<typeof schema>;
type FormOut = z.output<typeof schema>;

function toDefaults(r?: Other): FormIn {
  return {
    name: r?.name ?? "",
    category: r?.category ?? "",
    current_value: r ? String(r.current_value) : "",
    value_date: r?.value_date ?? todayISO(),
    invested_amount: r?.invested_amount == null ? "" : String(r.invested_amount),
    acquired_on: r?.acquired_on ?? "",
    notes: r?.notes ?? "",
  };
}

export function OtherForm({
  record,
  onSaved,
  onCancel,
}: {
  record?: Other;
  onSaved?: (record: Other) => void;
  onCancel?: () => void;
}) {
  const { control, handleSubmit } = useForm<FormIn, unknown, FormOut>({
    resolver: zodResolver(schema),
    defaultValues: toDefaults(record),
  });
  const { saving, save } = useAssetSave("other", record, onSaved);

  const onSubmit = handleSubmit((values) => {
    const payload: OtherInput = {
      name: values.name,
      category: values.category,
      current_value: values.current_value,
      value_date: values.value_date,
      invested_amount: values.invested_amount,
      acquired_on: values.acquired_on === "" ? null : values.acquired_on,
      notes: values.notes,
    };
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
        name="name"
        label="Name"
        placeholder="e.g. Bitcoin"
        required
      />
      <CategoryField control={control} name="category" label="Category" required />
      <TextField
        control={control}
        name="current_value"
        label="Current value"
        adornment="₹"
        inputMode="decimal"
        decimals={2}
        required
      />
      <DateField
        control={control}
        name="value_date"
        label="Value as of"
        maxDate={maxFutureDateISO()}
        required
      />
      <TextField
        control={control}
        name="invested_amount"
        label="Amount invested"
        adornment="₹"
        inputMode="decimal"
        decimals={2}
      />
      <DateField
        control={control}
        name="acquired_on"
        label="Purchase date"
        maxDate={maxFutureDateISO()}
      />
      <div className="sm:col-span-2">
        <NotesField control={control} name="notes" />
      </div>
    </FormShell>
  );
}

"use client";

import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  GOLD_FORM_LABELS,
  GOLD_PURITY_LABELS,
  type Gold,
  type GoldForm as GoldFormValue,
  type GoldInput,
  type GoldPurity,
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
  goldFormEnum,
  goldPurityEnum,
  goldWeight,
  maxFutureDateISO,
  moneyNumber,
  notesText,
  requiredText,
  startDateString,
} from "./schema";
import { useAssetSave } from "./use-asset-form";
import { useGoldRateAutofill } from "./use-gold-rate-autofill";

const schema = z.object({
  name: requiredText,
  form: goldFormEnum,
  purity: goldPurityEnum,
  weight_grams: goldWeight,
  purchase_date: startDateString,
  invested_amount: moneyNumber,
  notes: notesText,
});

type FormIn = z.input<typeof schema>;
type FormOut = z.output<typeof schema>;

const FORM_OPTIONS = toOptions(GOLD_FORM_LABELS);
const PURITY_OPTIONS = toOptions(GOLD_PURITY_LABELS);

function toDefaults(r?: Gold): FormIn {
  return {
    name: r?.name ?? "",
    // Blank until chosen; the schema then reports "Choose a form/purity".
    form: r?.form ?? ("" as GoldFormValue),
    purity: r?.purity ?? ("" as GoldPurity),
    weight_grams: r ? String(r.weight_grams) : "",
    purchase_date: r?.purchase_date ?? "",
    invested_amount: r ? String(r.invested_amount) : "",
    notes: r?.notes ?? "",
  };
}

export function GoldForm({
  record,
  onSaved,
  onCancel,
}: {
  record?: Gold;
  onSaved?: (record: Gold) => void;
  onCancel?: () => void;
}) {
  const { control, handleSubmit, setValue } = useForm<FormIn, unknown, FormOut>({
    resolver: zodResolver(schema),
    defaultValues: toDefaults(record),
  });
  const [purity, purchaseDate, weight, invested] = useWatch({
    control,
    name: ["purity", "purchase_date", "weight_grams", "invested_amount"],
  });
  const rateHint = useGoldRateAutofill({
    enabled: true,
    purity: String(purity ?? ""),
    purchaseDate: String(purchaseDate ?? ""),
    weight: String(weight ?? ""),
    invested: String(invested ?? ""),
    setValue,
  });
  const { saving, save } = useAssetSave("gold", record, onSaved);

  const onSubmit = handleSubmit((values) => {
    const payload: GoldInput = {
      name: values.name,
      form: values.form,
      purity: values.purity,
      weight_grams: values.weight_grams,
      purchase_date: values.purchase_date,
      invested_amount: values.invested_amount,
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
        placeholder="e.g. Wedding necklace"
        required
      />
      <DateField
        control={control}
        name="purchase_date"
        label="Purchase date"
        maxDate={maxFutureDateISO()}
        required
      />
      <SelectField
        control={control}
        name="form"
        label="Form"
        options={FORM_OPTIONS}
        required
      />
      <SelectField
        control={control}
        name="purity"
        label="Purity"
        options={PURITY_OPTIONS}
        required
      />
      <TextField
        control={control}
        name="weight_grams"
        label="Weight (grams)"
        inputMode="decimal"
        decimals={3}
        required
      />
      <TextField
        control={control}
        name="invested_amount"
        label="Total invested"
        adornment="₹"
        inputMode="decimal"
        decimals={2}
        hint={
          rateHint ??
          "Gold value on the purchase day, excluding making charges and GST"
        }
        required
      />
      <div className="sm:col-span-2">
        <NotesField control={control} name="notes" />
      </div>
    </FormShell>
  );
}

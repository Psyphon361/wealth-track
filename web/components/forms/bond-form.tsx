"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { BOND_TYPE_LABELS, type Bond, type BondInput } from "@/lib/types";
import { FormShell } from "./form-shell";
import {
  DateField,
  NotesField,
  SelectField,
  TextField,
  toOptions,
} from "./fields";
import {
  bondTypeEnum,
  dateString,
  optionalText,
  positiveInteger,
  positiveNumber,
  requiredText,
} from "./schema";
import { useAssetSave } from "./use-asset-form";

const schema = z
  .object({
    name: requiredText,
    isin: optionalText,
    issuer: requiredText,
    bond_type: bondTypeEnum,
    platform: optionalText,
    quantity: positiveInteger,
    face_value: positiveNumber,
    purchase_price: positiveNumber,
    purchase_date: dateString,
    ytm: positiveNumber,
    maturity_date: dateString,
    notes: optionalText,
  })
  .refine(
    (v) =>
      v.purchase_date === "" ||
      v.maturity_date === "" ||
      v.maturity_date > v.purchase_date,
    {
      message: "Maturity date must be after the purchase date",
      path: ["maturity_date"],
    },
  );

type FormIn = z.input<typeof schema>;
type FormOut = z.output<typeof schema>;

const BOND_TYPE_OPTIONS = toOptions(BOND_TYPE_LABELS);

function toDefaults(r?: Bond): FormIn {
  return {
    name: r?.name ?? "",
    isin: r?.isin ?? "",
    issuer: r?.issuer ?? "",
    bond_type: r?.bond_type ?? "government",
    platform: r?.platform ?? "",
    quantity: r ? String(r.quantity) : "",
    face_value: r?.face_value != null ? String(r.face_value) : "",
    purchase_price: r ? String(r.purchase_price) : "",
    purchase_date: r?.purchase_date ?? "",
    ytm: r ? String(r.ytm) : "",
    maturity_date: r?.maturity_date ?? "",
    notes: r?.notes ?? "",
  };
}

export function BondForm({
  record,
  onSaved,
  onCancel,
}: {
  record?: Bond;
  onSaved?: (record: Bond) => void;
  onCancel?: () => void;
}) {
  const { saving, save } = useAssetSave("bond", record, onSaved);
  const { control, handleSubmit } = useForm<FormIn, unknown, FormOut>({
    resolver: zodResolver(schema),
    defaultValues: toDefaults(record),
  });
  const onSubmit = handleSubmit((values) => {
    const payload: BondInput = values;
    return save(payload);
  });

  return (
    <FormShell
      onSubmit={onSubmit}
      saving={saving}
      editing={!!record}
      onCancel={onCancel}
    >
      <TextField control={control} name="name" label="Bond name" required />
      <TextField control={control} name="isin" label="ISIN" />
      <TextField control={control} name="issuer" label="Issuer" required />
      <SelectField
        control={control}
        name="bond_type"
        label="Bond type"
        options={BOND_TYPE_OPTIONS}
        required
      />
      <TextField control={control} name="platform" label="Platform" />
      <TextField
        control={control}
        name="quantity"
        label="Quantity"
        inputMode="numeric"
        decimals={0}
        required
      />
      <TextField
        control={control}
        name="face_value"
        label="Face value per unit"
        adornment="₹"
        inputMode="decimal"
        decimals={2}
        required
      />
      <TextField
        control={control}
        name="purchase_price"
        label="Purchase price per unit"
        adornment="₹"
        inputMode="decimal"
        decimals={2}
        required
      />
      <DateField
        control={control}
        name="purchase_date"
        label="Purchase date"
        required
      />
      <TextField
        control={control}
        name="ytm"
        label="Yield to maturity p.a."
        adornment="%"
        inputMode="decimal"
        required
      />
      <DateField
        control={control}
        name="maturity_date"
        label="Maturity date"
        required
      />
      <div className="sm:col-span-2">
        <NotesField control={control} name="notes" />
      </div>
    </FormShell>
  );
}

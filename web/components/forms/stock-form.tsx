"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { EXCHANGE_LABELS, type Stock, type StockInput } from "@/lib/types";
import { FormShell } from "./form-shell";
import { NotesField, SelectField, TextField, toOptions } from "./fields";
import {
  dateString,
  exchangeEnum,
  optionalText,
  positiveInteger,
  positiveNumber,
  requiredText,
} from "./schema";
import { useAssetSave } from "./use-asset-form";

const schema = z.object({
  name: requiredText,
  symbol: optionalText,
  exchange: exchangeEnum,
  broker: optionalText,
  quantity: positiveInteger,
  avg_buy_price: positiveNumber,
  buy_date: dateString,
  notes: optionalText,
});

type FormIn = z.input<typeof schema>;
type FormOut = z.output<typeof schema>;

const EXCHANGE_OPTIONS = toOptions(EXCHANGE_LABELS);

function toDefaults(r?: Stock): FormIn {
  return {
    name: r?.name ?? "",
    symbol: r?.symbol ?? "",
    exchange: r?.exchange ?? "NSE",
    broker: r?.broker ?? "",
    quantity: r ? String(r.quantity) : "",
    avg_buy_price: r ? String(r.avg_buy_price) : "",
    buy_date: r?.buy_date ?? "",
    notes: r?.notes ?? "",
  };
}

export function StockForm({
  record,
  onSaved,
  onCancel,
}: {
  record?: Stock;
  onSaved?: (record: Stock) => void;
  onCancel?: () => void;
}) {
  const { saving, save } = useAssetSave("stock", record, onSaved);
  const { control, handleSubmit } = useForm<FormIn, unknown, FormOut>({
    resolver: zodResolver(schema),
    defaultValues: toDefaults(record),
  });
  const onSubmit = handleSubmit((values) => {
    const payload: StockInput = values;
    return save(payload);
  });

  return (
    <FormShell
      onSubmit={onSubmit}
      saving={saving}
      editing={!!record}
      onCancel={onCancel}
    >
      <TextField control={control} name="name" label="Company name" required />
      <TextField control={control} name="symbol" label="Symbol" />
      <SelectField
        control={control}
        name="exchange"
        label="Exchange"
        options={EXCHANGE_OPTIONS}
        required
      />
      <TextField control={control} name="broker" label="Broker" />
      <TextField
        control={control}
        name="quantity"
        label="Quantity"
        inputMode="numeric"
        required
      />
      <TextField
        control={control}
        name="avg_buy_price"
        label="Average buy price"
        adornment="₹"
        inputMode="decimal"
        required
      />
      <TextField
        control={control}
        name="buy_date"
        label="Buy date"
        type="date"
        required
      />
      <div className="sm:col-span-2">
        <NotesField control={control} name="notes" />
      </div>
    </FormShell>
  );
}

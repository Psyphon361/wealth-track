"use client";

import { useEffect, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { apiGet } from "@/lib/api";
import type { Nps, NpsInput, NpsScheme } from "@/lib/types";
import { Field, FieldLabel } from "@/components/ui/field";
import { FormShell } from "./form-shell";
import { DateField, FormError, NotesField, TextField } from "./fields";
import { NpsSchemePicker } from "./nps-scheme-picker";
import {
  maxFutureDateISO,
  moneyNumber,
  notesText,
  NPS_SCHEME_ERROR,
  npsUnits,
  startDateString,
} from "./schema";
import { useAssetSave } from "./use-asset-form";

const schema = z.object({
  scheme_id: z.string().min(1, NPS_SCHEME_ERROR),
  scheme_name: z.string(),
  units: npsUnits,
  contributed: moneyNumber,
  start_date: startDateString,
  notes: notesText,
});

type FormIn = z.input<typeof schema>;
type FormOut = z.output<typeof schema>;

function toDefaults(r?: Nps): FormIn {
  return {
    scheme_id: r?.scheme_id ?? "",
    scheme_name: r?.scheme_name ?? "",
    units: r ? String(r.units) : "",
    contributed: r ? String(r.contributed) : "",
    start_date: r?.start_date ?? "",
    notes: r?.notes ?? "",
  };
}

export function NpsForm({
  record,
  onSaved,
  onCancel,
}: {
  record?: Nps;
  onSaved?: (record: Nps) => void;
  onCancel?: () => void;
}) {
  const { control, handleSubmit, setValue, setError } = useForm<
    FormIn,
    unknown,
    FormOut
  >({
    resolver: zodResolver(schema),
    defaultValues: toDefaults(record),
  });
  const { saving, save, duplicate } = useAssetSave("nps", record, onSaved, (issues) => {
    for (const i of issues) {
      if (i.field === "scheme_id") {
        setError("scheme_id", { type: "server", message: i.message });
      }
    }
  });
  // Master details for the summary line (selected, or fetched when editing).
  const [meta, setMeta] = useState<NpsScheme | null>(null);

  const initialId = record?.scheme_id ?? null;
  useEffect(() => {
    if (initialId === null) return;
    let cancelled = false;
    apiGet<NpsScheme>(`/master/nps/${encodeURIComponent(initialId)}`)
      .then((s) => {
        if (!cancelled) setMeta(s);
      })
      .catch(() => {
        // 404 or network: keep showing the stored name.
      });
    return () => {
      cancelled = true;
    };
  }, [initialId]);

  const onSubmit = handleSubmit((values) => {
    const payload: NpsInput = {
      scheme_id: values.scheme_id,
      units: values.units,
      contributed: values.contributed,
      start_date: values.start_date,
      notes: values.notes,
    };
    return save(payload);
  });

  return (
    <FormShell
      onSubmit={onSubmit}
      saving={saving}
      editing={!!record}
      duplicate={duplicate}
      onCancel={onCancel}
    >
      <div className="sm:col-span-2">
        <Controller
          control={control}
          name="scheme_id"
          render={({ field, fieldState }) => (
            <Field data-invalid={fieldState.invalid} className="gap-1.5">
              <FieldLabel
                htmlFor="scheme_id"
                className="text-xs font-normal text-muted-foreground"
              >
                Scheme
              </FieldLabel>
              <NpsSchemePicker
                id="scheme_id"
                value={
                  field.value
                    ? {
                        scheme_id: field.value,
                        name: meta?.scheme_name ?? record?.scheme_name ?? "",
                      }
                    : null
                }
                scheme={meta}
                invalid={fieldState.invalid}
                onBlur={field.onBlur}
                onSelect={(s) => {
                  setMeta(s);
                  field.onChange(s.scheme_id);
                  setValue("scheme_name", s.scheme_name);
                }}
              />
              <FormError error={fieldState.error} />
            </Field>
          )}
        />
      </div>
      <TextField
        control={control}
        name="units"
        label="Units"
        inputMode="decimal"
        decimals={4}
        required
      />
      <TextField
        control={control}
        name="contributed"
        label="Total contributed"
        adornment="₹"
        inputMode="decimal"
        decimals={2}
        hint="Your + employer contributions to date"
        required
      />
      <DateField
        control={control}
        name="start_date"
        label="Started on"
        maxDate={maxFutureDateISO()}
        required
      />
      <div className="sm:col-span-2">
        <NotesField control={control} name="notes" />
      </div>
    </FormShell>
  );
}

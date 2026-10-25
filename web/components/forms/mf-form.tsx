"use client";

import { useEffect, useState } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { apiGet } from "@/lib/api";
import {
  MF_CATEGORY_LABELS,
  type MfScheme,
  type MutualFund,
  type MutualFundInput,
} from "@/lib/types";
import { Field, FieldLabel } from "@/components/ui/field";
import { FormShell } from "./form-shell";
import {
  DateField,
  FormError,
  NotesField,
  SelectField,
  TextField,
  toOptions,
} from "./fields";
import {
  MAX_TEXT,
  SCHEME_REQUIRED_ERROR,
  maxFutureDateISO,
  mfCategoryEnum,
  moneyNumber,
  notesText,
  optionalText,
  positiveUnits,
  startDateString,
} from "./schema";
import { SchemePicker } from "./scheme-picker";
import { useAssetSave } from "./use-asset-form";
import { useNavAutofill } from "./use-nav-autofill";

const schema = z
  .object({
    scheme_mode: z.enum(["picker", "manual"]),
    scheme_code: z.number().nullable(),
    scheme_name: z
      .string()
      .trim()
      .max(MAX_TEXT, `Must be at most ${MAX_TEXT} characters`),
    platform: optionalText,
    category: mfCategoryEnum,
    units: positiveUnits,
    avg_nav: moneyNumber,
    purchase_date: startDateString,
    notes: notesText,
  })
  .superRefine((v, ctx) => {
    if (v.scheme_mode === "picker") {
      if (v.scheme_code === null) {
        ctx.addIssue({
          code: "custom",
          path: ["scheme_code"],
          message: SCHEME_REQUIRED_ERROR,
        });
      }
    } else if (v.scheme_name === "") {
      ctx.addIssue({
        code: "custom",
        path: ["scheme_name"],
        message: "Required",
      });
    }
  });

type FormIn = z.input<typeof schema>;
type FormOut = z.output<typeof schema>;

const CATEGORY_OPTIONS = toOptions(MF_CATEGORY_LABELS);

const LINK_BUTTON =
  "w-fit text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline";

function toDefaults(r?: MutualFund): FormIn {
  return {
    scheme_mode: !r || r.scheme_code != null ? "picker" : "manual",
    scheme_code: r?.scheme_code ?? null,
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
  const { control, handleSubmit, setValue, setError, clearErrors } = useForm<
    FormIn,
    unknown,
    FormOut
  >({
    resolver: zodResolver(schema),
    defaultValues: toDefaults(record),
  });
  const { saving, save } = useAssetSave("mf", record, onSaved, (issues) => {
    for (const i of issues) {
      if (i.field === "scheme_code") {
        setError("scheme_code", { type: "server", message: i.message });
      }
    }
  });
  const mode = useWatch({ control, name: "scheme_mode" });
  const schemeName = useWatch({ control, name: "scheme_name" });
  const schemeCode = useWatch({ control, name: "scheme_code" });
  const purchaseDate = useWatch({ control, name: "purchase_date" });
  const avgNav = useWatch({ control, name: "avg_nav" });
  const navHint = useNavAutofill({
    enabled: mode === "picker",
    schemeCode,
    purchaseDate: String(purchaseDate ?? ""),
    avgNav: String(avgNav ?? ""),
    setValue,
  });
  // Master details for the summary line (selected, or fetched when editing).
  const [meta, setMeta] = useState<MfScheme | null>(null);

  const initialCode = record?.scheme_code ?? null;
  useEffect(() => {
    if (initialCode === null) return;
    let cancelled = false;
    apiGet<MfScheme>(`/master/mf/${initialCode}`)
      .then((s) => {
        if (!cancelled) setMeta(s);
      })
      .catch(() => {
        // 404 or network: keep showing the stored name.
      });
    return () => {
      cancelled = true;
    };
  }, [initialCode]);

  function switchMode(next: "picker" | "manual") {
    setValue("scheme_mode", next);
    setValue("scheme_code", null);
    setMeta(null);
    clearErrors(["scheme_code", "scheme_name"]);
  }

  const onSubmit = handleSubmit((values) => {
    const manual = values.scheme_mode === "manual";
    const payload: MutualFundInput = {
      scheme_code: manual ? null : values.scheme_code,
      scheme_name: values.scheme_name,
      platform: values.platform,
      category: values.category,
      units: values.units,
      avg_nav: values.avg_nav,
      purchase_date: values.purchase_date,
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
      <div className="flex flex-col gap-1.5 sm:col-span-2">
        {mode === "picker" ? (
          <Controller
            control={control}
            name="scheme_code"
            render={({ field, fieldState }) => (
              <Field data-invalid={fieldState.invalid} className="gap-1.5">
                <FieldLabel
                  htmlFor="scheme_code"
                  className="text-xs font-normal text-muted-foreground"
                >
                  Scheme
                </FieldLabel>
                <SchemePicker
                  id="scheme_code"
                  value={
                    field.value !== null
                      ? { scheme_code: field.value, name: meta?.name ?? schemeName }
                      : null
                  }
                  scheme={meta}
                  invalid={fieldState.invalid}
                  onBlur={field.onBlur}
                  onSelect={(s) => {
                    setMeta(s);
                    field.onChange(s.scheme_code);
                    setValue("scheme_name", s.name);
                    setValue("category", s.category);
                  }}
                />
                <FormError error={fieldState.error} />
              </Field>
            )}
          />
        ) : (
          <TextField
            control={control}
            name="scheme_name"
            label="Scheme name"
            required
          />
        )}
        <button
          type="button"
          className={LINK_BUTTON}
          onClick={() => switchMode(mode === "picker" ? "manual" : "picker")}
        >
          {mode === "picker"
            ? "Not listed? Enter manually"
            : "Search the scheme list instead"}
        </button>
      </div>
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
        decimals={3}
        required
      />
      <TextField
        control={control}
        name="avg_nav"
        label="Average NAV"
        adornment="₹"
        inputMode="decimal"
        decimals={4}
        hint={navHint}
        required
      />
      <DateField
        control={control}
        name="purchase_date"
        label="Purchase date"
        maxDate={maxFutureDateISO()}
        required
      />
      <div className="sm:col-span-2">
        <NotesField control={control} name="notes" />
      </div>
    </FormShell>
  );
}

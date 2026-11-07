"use client";

import { useState } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  COMPOUNDING_LABELS,
  type RecurringDeposit,
  type RecurringDepositInput,
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
  IssuerModeToggle,
  IssuerPicker,
  issuerMain,
  useIssuerMeta,
} from "./issuer-picker";
import {
  FD_RATE_ERROR,
  ISSUER_REQUIRED_ERROR,
  MAX_TEXT,
  RD_TENURE_ERROR,
  TENURE_ERROR,
  compoundingEnum,
  maxFutureDateISO,
  moneyNumber,
  notesText,
  optionalText,
  rateNumber,
  startDateString,
  tenureIsPositive,
  tenureOk,
  tenurePart,
} from "./schema";
import { TenureField } from "./tenure-field";
import { useAssetSave } from "./use-asset-form";
import { usePaidFrom } from "./paid-from-field";
import type { ReinvestPrefill } from "@/lib/reinvest";

const schema = z
  .object({
    master_mode: z.enum(["picker", "manual"]),
    issuer_id: z.number().nullable(),
    bank: z
      .string()
      .trim()
      .max(MAX_TEXT, `Must be at most ${MAX_TEXT} characters`),
    label: optionalText,
    monthly_instalment: moneyNumber,
    rate: rateNumber(15, FD_RATE_ERROR),
    start_date: startDateString,
    tenure_years: tenurePart,
    tenure_months: tenurePart,
    tenure_days: tenurePart,
    maturity_date: z.string(),
    compounding: compoundingEnum,
    notes: notesText,
  })
  .superRefine((v, ctx) => {
    if (v.master_mode === "picker") {
      if (v.issuer_id === null) {
        ctx.addIssue({
          code: "custom",
          path: ["issuer_id"],
          message: ISSUER_REQUIRED_ERROR,
        });
      }
    } else if (v.bank === "") {
      ctx.addIssue({ code: "custom", path: ["bank"], message: "Required" });
    }
  })
  .refine(tenureIsPositive, {
    message: TENURE_ERROR,
    path: ["tenure_years"],
  })
  .refine((v) => tenureOk("rd", v), {
    message: RD_TENURE_ERROR,
    path: ["tenure_years"],
  });

type FormIn = z.input<typeof schema>;
type FormOut = z.output<typeof schema>;

const COMPOUNDING_OPTIONS = toOptions(COMPOUNDING_LABELS);

/** A saved record (edit) or prefilled values for a new one. */
function toDefaults(
  r?: RecurringDeposit,
  d?: Partial<RecurringDepositInput>,
): FormIn {
  const s: Partial<RecurringDepositInput> | undefined = r ?? d;
  const manual = r ? r.issuer_id == null : !!d && d.issuer_id == null && !!d.bank;
  return {
    master_mode: manual ? "manual" : "picker",
    issuer_id: s?.issuer_id ?? null,
    bank: s?.bank ?? "",
    label: s?.label ?? "",
    monthly_instalment:
      s?.monthly_instalment != null ? String(s.monthly_instalment) : "",
    rate: s?.rate != null ? String(s.rate) : "",
    start_date: s?.start_date ?? "",
    tenure_years: String(s?.tenure_years ?? 0),
    tenure_months: String(s?.tenure_months ?? 0),
    tenure_days: String(s?.tenure_days ?? 0),
    maturity_date: "",
    compounding: s?.compounding ?? "quarterly",
    notes: s?.notes ?? "",
  };
}

export function RdForm({
  record,
  defaults,
  submit,
  submitLabel,
  onSaved,
  onCancel,
  reinvest,
}: {
  /** One-shot prefill from "Reinvest" (create only). */
  reinvest?: ReinvestPrefill | null;
  record?: RecurringDeposit;
  /** Prefill a new RD (ignored when `record` is given). */
  defaults?: Partial<RecurringDepositInput>;
  /** Takes the payload instead of POSTing /api/assets/rd (the form still locks while it runs). */
  submit?: (payload: RecurringDepositInput) => Promise<void> | void;
  submitLabel?: string;
  onSaved?: (record: RecurringDeposit) => void;
  onCancel?: () => void;
}) {
  const { control, handleSubmit, setValue, setError, clearErrors, trigger } = useForm<
    FormIn,
    unknown,
    FormOut
  >({
    resolver: zodResolver(schema),
    defaultValues: toDefaults(record, defaults),
  });
  const [submitting, setSubmitting] = useState(false);
  const pf = usePaidFrom({ type: "rd", record, control, setValue, reinvest });
  const { saving: assetSaving, save, duplicate } = useAssetSave("rd", record, onSaved, (issues) => {
    pf.applyIssues(issues);
    for (const i of issues) {
      if (i.field === "issuer_id") {
        setError("issuer_id", { type: "server", message: i.message });
      }
    }
  });
  const saving = assetSaving || submitting;
  const mode = useWatch({ control, name: "master_mode" });
  const bankText = useWatch({ control, name: "bank" });
  const [meta, setMeta] = useIssuerMeta((record ?? defaults)?.issuer_id ?? null);

  function switchMode(next: "picker" | "manual") {
    setValue("master_mode", next);
    setValue("issuer_id", null);
    setMeta(null);
    clearErrors(["issuer_id", "bank"]);
  }
  const onSubmit = handleSubmit((values) => {
    if (!submit && pf.error) return;
    const { master_mode, ...withMaturity } = values;
    const rest: Partial<typeof withMaturity> = { ...withMaturity };
    delete rest.maturity_date;
    const payload: RecurringDepositInput = {
      ...(rest as Omit<typeof withMaturity, "maturity_date">),
      issuer_id: master_mode === "manual" ? null : values.issuer_id,
    };
    if (!submit) return save({ ...payload, ...pf.body });
    setSubmitting(true);
    return Promise.resolve(submit(payload)).finally(() => setSubmitting(false));
  });

  return (
    <FormShell
      onSubmit={onSubmit}
      saving={saving}
      editing={!!record}
      duplicate={duplicate}
      paidFrom={submit ? undefined : pf}
      submitLabel={submitLabel}
      onCancel={onCancel}
    >
      <div className="flex flex-col gap-1.5 sm:col-span-2">
        {mode === "picker" ? (
          <Controller
            control={control}
            name="issuer_id"
            render={({ field, fieldState }) => (
              <Field data-invalid={fieldState.invalid} className="gap-1.5">
                <FieldLabel
                  htmlFor="issuer_id"
                  className="text-xs font-normal text-muted-foreground"
                >
                  Bank / issuer
                </FieldLabel>
                <IssuerPicker
                  id="issuer_id"
                  hasValue={field.value !== null}
                  meta={meta}
                  bankText={bankText}
                  invalid={fieldState.invalid}
                  onBlur={field.onBlur}
                  onSelect={(s) => {
                    setMeta(s);
                    field.onChange(s.id);
                    setValue("bank", issuerMain(s));
                  }}
                />
                <FormError error={fieldState.error} />
              </Field>
            )}
          />
        ) : (
          <TextField control={control} name="bank" label="Bank" required />
        )}
        <IssuerModeToggle mode={mode} onChange={switchMode} />
      </div>
      <TextField control={control} name="label" label="Label" />
      <TextField
        control={control}
        name="monthly_instalment"
        label="Monthly instalment"
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
        label="Compounding"
        options={COMPOUNDING_OPTIONS}
        required
      />
      <TenureField control={control} setValue={setValue} trigger={trigger} />
      <div className="sm:col-span-2">
        <NotesField control={control} name="notes" />
      </div>
    </FormShell>
  );
}

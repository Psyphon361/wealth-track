"use client";

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

function toDefaults(r?: RecurringDeposit): FormIn {
  return {
    master_mode: !r || r.issuer_id != null ? "picker" : "manual",
    issuer_id: r?.issuer_id ?? null,
    bank: r?.bank ?? "",
    label: r?.label ?? "",
    monthly_instalment: r ? String(r.monthly_instalment) : "",
    rate: r ? String(r.rate) : "",
    start_date: r?.start_date ?? "",
    tenure_years: String(r?.tenure_years ?? 0),
    tenure_months: String(r?.tenure_months ?? 0),
    tenure_days: String(r?.tenure_days ?? 0),
    maturity_date: "",
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
  const { control, handleSubmit, setValue, setError, clearErrors, trigger } = useForm<
    FormIn,
    unknown,
    FormOut
  >({
    resolver: zodResolver(schema),
    defaultValues: toDefaults(record),
  });
  const { saving, save } = useAssetSave("rd", record, onSaved, (issues) => {
    for (const i of issues) {
      if (i.field === "issuer_id") {
        setError("issuer_id", { type: "server", message: i.message });
      }
    }
  });
  const mode = useWatch({ control, name: "master_mode" });
  const bankText = useWatch({ control, name: "bank" });
  const [meta, setMeta] = useIssuerMeta(record?.issuer_id ?? null);

  function switchMode(next: "picker" | "manual") {
    setValue("master_mode", next);
    setValue("issuer_id", null);
    setMeta(null);
    clearErrors(["issuer_id", "bank"]);
  }
  const onSubmit = handleSubmit((values) => {
    const { master_mode, ...withMaturity } = values;
    const rest: Partial<typeof withMaturity> = { ...withMaturity };
    delete rest.maturity_date;
    const payload: RecurringDepositInput = {
      ...(rest as Omit<typeof withMaturity, "maturity_date">),
      issuer_id: master_mode === "manual" ? null : values.issuer_id,
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

"use client";

import { useMemo, useState } from "react";
import {
  Controller,
  useForm,
  useWatch,
  type Control,
} from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Field, FieldLabel } from "@/components/ui/field";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { apiPost } from "@/lib/api";
import { confirmDuplicatePath } from "@/lib/duplicates";
import { markHoldingsStale } from "@/lib/holdings-cache";
import { invalidateNetWorth } from "@/lib/networth-cache";
import { notify } from "@/lib/notify";
import { SIPS_VIEW_HREF, pastHint, pastQuestion } from "@/lib/sip";
import type { MfScheme, SipInput, SipResult } from "@/lib/types";
import { DayOfMonthField } from "./day-of-month-field";
import { useDuplicateWarning } from "./duplicate-dialog";
import {
  DateField,
  FormError,
  SelectField,
  TextField,
  type Option,
} from "./fields";
import { useFormDisabled } from "./form-disabled";
import { FormShell } from "./form-shell";
import {
  SCHEME_REQUIRED_ERROR,
  isValidISODate,
  maxSipStartDateISO,
  requiredText,
  sipAmount,
  sipDay,
  sipStartDate,
  todayISO,
} from "./schema";
import { SchemePicker } from "./scheme-picker";
import { fieldIssues, type FieldIssue } from "./use-asset-form";
import { useFundHoldings } from "./use-fund-holdings";

const NEW_HOLDING = "new";

const schema = z
  .object({
    scheme_code: z.number().nullable(),
    mutual_fund_id: z.string(),
    platform: requiredText,
    amount: sipAmount,
    day_of_month: sipDay,
    start_date: sipStartDate,
    include_past: z.enum(["yes", "no"]),
  })
  .superRefine((v, ctx) => {
    if (v.scheme_code === null) {
      ctx.addIssue({
        code: "custom",
        path: ["scheme_code"],
        message: SCHEME_REQUIRED_ERROR,
      });
    }
  });

type FormIn = z.input<typeof schema>;
type FormOut = z.output<typeof schema>;

const FORM_FIELDS = [
  "scheme_code",
  "mutual_fund_id",
  "platform",
  "amount",
  "day_of_month",
  "start_date",
] as const;

const units3 = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 3,
  maximumFractionDigits: 3,
});

const defaults: FormIn = {
  scheme_code: null,
  mutual_fund_id: NEW_HOLDING,
  platform: "",
  amount: "",
  day_of_month: "",
  start_date: "",
  include_past: "yes",
};

/** Create a SIP; a 409 duplicate warning opens the dialog instead of a toast. */
function useSipCreate(
  onSaved: (() => void) | undefined,
  onIssues: (issues: FieldIssue[]) => void,
) {
  const [saving, setSaving] = useState(false);
  const warning = useDuplicateWarning(() => SIPS_VIEW_HREF);

  function done(saved: SipResult) {
    invalidateNetWorth();
    markHoldingsStale("mf");
    notify.success(saved);
    onSaved?.();
  }

  function failed(e: unknown) {
    notify.error(e);
    const issues = fieldIssues(e);
    if (issues.length) onIssues(issues);
  }

  async function create(payload: SipInput): Promise<void> {
    setSaving(true);
    try {
      done(await apiPost<SipResult>("/sips", payload));
    } catch (e) {
      const confirmed = async () => {
        try {
          done(
            await apiPost<SipResult>(confirmDuplicatePath("/sips"), payload),
          );
        } catch (err) {
          failed(err);
        }
      };
      if (!warning.intercept(e, confirmed)) failed(e);
    } finally {
      setSaving(false);
    }
  }

  return {
    saving: saving || warning.busy,
    create,
    duplicate: warning.props,
  };
}

export function SipForm({
  onSaved,
  onCancel,
}: {
  onSaved?: () => void;
  onCancel?: () => void;
}) {
  const { control, handleSubmit, setValue, setError, clearErrors } = useForm<
    FormIn,
    unknown,
    FormOut
  >({
    resolver: zodResolver(schema),
    defaultValues: defaults,
  });
  const { saving, create, duplicate } = useSipCreate(onSaved, (issues) => {
    for (const i of issues) {
      const name = FORM_FIELDS.find((f) => f === i.field);
      if (name) setError(name, { type: "server", message: i.message });
    }
  });
  const [meta, setMeta] = useState<MfScheme | null>(null);
  const { holdings, failed } = useFundHoldings();

  const schemeCode = useWatch({ control, name: "scheme_code" });
  const startDate = useWatch({ control, name: "start_date" });
  const dayStr = useWatch({ control, name: "day_of_month" });
  const addTo = useWatch({ control, name: "mutual_fund_id" });

  const held = useMemo(
    () =>
      schemeCode === null
        ? []
        : (holdings ?? []).filter((h) => h.scheme_code === schemeCode),
    [holdings, schemeCode],
  );
  const addToOptions: Option[] = useMemo(
    () => [
      ...held.map((h) => ({
        value: String(h.id),
        label: `${h.platform || "No Platform"} · ${units3.format(h.units)} units`,
      })),
      { value: NEW_HOLDING, label: "A New Holding" },
    ],
    [held],
  );

  const day = Number(dayStr);
  const question =
    isValidISODate(String(startDate)) && Number.isInteger(day)
      ? pastQuestion(String(startDate), day, todayISO())
      : null;
  const checkingHoldings =
    schemeCode !== null && holdings === null && !failed;

  const onSubmit = handleSubmit((values) => {
    const include = values.include_past === "yes" && question !== null;
    return create({
      scheme_code: values.scheme_code as number,
      platform: values.platform,
      amount: values.amount,
      day_of_month: values.day_of_month,
      start_date: values.start_date,
      include_past: include,
      mutual_fund_id:
        values.mutual_fund_id === NEW_HOLDING
          ? null
          : Number(values.mutual_fund_id),
    });
  });

  return (
    <FormShell
      onSubmit={onSubmit}
      saving={saving}
      editing={false}
      submitLabel="Start SIP"
      duplicate={duplicate}
      onCancel={onCancel}
    >
      <div className="flex flex-col gap-1.5 sm:col-span-2">
        <Controller
          control={control}
          name="scheme_code"
          render={({ field, fieldState }) => (
            <Field data-invalid={fieldState.invalid} className="gap-1.5">
              <FieldLabel
                htmlFor="scheme_code"
                className="text-xs font-normal text-muted-foreground"
              >
                Fund
              </FieldLabel>
              <SchemePicker
                id="scheme_code"
                value={
                  field.value !== null
                    ? { scheme_code: field.value, name: meta?.name ?? "" }
                    : null
                }
                scheme={meta}
                invalid={fieldState.invalid}
                onBlur={field.onBlur}
                onSelect={(s) => {
                  setMeta(s);
                  field.onChange(s.scheme_code);
                  clearErrors("scheme_code");
                  const mine = (holdings ?? []).filter(
                    (h) => h.scheme_code === s.scheme_code,
                  );
                  if (mine.length === 1) {
                    setValue("mutual_fund_id", String(mine[0].id));
                    if (mine[0].platform) {
                      setValue("platform", mine[0].platform);
                    }
                  } else {
                    setValue("mutual_fund_id", NEW_HOLDING);
                  }
                }}
              />
              {checkingHoldings ? (
                <p className="text-[11px] text-muted-foreground">
                  Checking your holdings…
                </p>
              ) : null}
              <FormError error={fieldState.error} />
            </Field>
          )}
        />
      </div>
      {held.length > 0 ? (
        <div className="flex flex-col gap-1.5 sm:col-span-2">
          <SelectField
            control={control}
            name="mutual_fund_id"
            label="Add to"
            options={addToOptions}
            required
            onChange={(v) => {
              const picked = held.find((h) => String(h.id) === v);
              if (picked?.platform) setValue("platform", picked.platform);
            }}
          />
          <p className="text-[11px] text-muted-foreground">
            {addTo === NEW_HOLDING
              ? "You already hold this fund. Pick a holding to add the instalments to it, or leave A New Holding to create a separate one."
              : "Each instalment adds units to this holding."}
          </p>
        </div>
      ) : null}
      <TextField control={control} name="platform" label="Platform" required />
      <TextField
        control={control}
        name="amount"
        label="Monthly amount"
        adornment="₹"
        inputMode="decimal"
        decimals={2}
        required
      />
      <DayOfMonthField
        control={control}
        name="day_of_month"
        label="SIP date"
        required
      />
      <DateField
        control={control}
        name="start_date"
        label="Start date"
        maxDate={maxSipStartDateISO()}
        required
      />
      {question ? (
        <PastChoice question={question} control={control} />
      ) : null}
    </FormShell>
  );
}

/** Themed Yes/No for adding the instalments that fell before today. */
function PastChoice({
  question,
  control,
}: {
  question: string;
  control: Control<FormIn, unknown, FormOut>;
}) {
  const locked = useFormDisabled();
  return (
    <Controller
      control={control}
      name="include_past"
      render={({ field }) => (
        <div
          role="group"
          aria-labelledby="include_past_label"
          className="flex flex-col gap-1.5 sm:col-span-2"
        >
          <p
            id="include_past_label"
            className="text-xs text-muted-foreground"
          >
            {question}
          </p>
          <ToggleGroup
            value={[field.value]}
            disabled={locked}
            onValueChange={(v) => {
              if (v[0]) field.onChange(v[0]);
            }}
            variant="outline"
            size="sm"
            spacing={0}
            className="h-7 self-start"
          >
            <ToggleGroupItem value="yes" className="h-7 px-4 text-[13.5px]">
              Yes
            </ToggleGroupItem>
            <ToggleGroupItem value="no" className="h-7 px-4 text-[13.5px]">
              No
            </ToggleGroupItem>
          </ToggleGroup>
          <p className="text-[11px] text-muted-foreground">
            {pastHint(field.value === "yes")}
          </p>
        </div>
      )}
    />
  );
}

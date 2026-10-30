"use client";

import { useEffect, useRef, useState } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { apiGet } from "@/lib/api";
import {
  BOND_PRECISION,
  bondAmountsConsistent,
  deriveAmount,
  type AmountField,
} from "@/lib/holding-amounts";
import { formatDate } from "@/lib/format";
import {
  BOND_TYPE_LABELS,
  type Bond,
  type BondInput,
  type BondMaster,
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
import { MasterPicker } from "./master-picker";
import {
  BOND_AMOUNT_MISMATCH_ERROR,
  BOND_REQUIRED_ERROR,
  MATURITY_RANGE_ERROR,
  MAX_BOND_YEARS,
  MAX_ISIN,
  MAX_TEXT,
  YTM_ERROR,
  addMonthsISO,
  bondTypeEnum,
  dateString,
  isValidISODate,
  isinText,
  maturityWithinLimit,
  maxFutureDateISO,
  moneyNumber,
  notesText,
  optionalText,
  positiveInteger,
  rateNumber,
  requiredText,
  startDateString,
  todayISO,
} from "./schema";
import { useAssetSave } from "./use-asset-form";

const schema = z
  .object({
    master_mode: z.enum(["picker", "manual"]),
    master_id: z.number().nullable(),
    name: z
      .string()
      .trim()
      .max(MAX_TEXT, `Must be at most ${MAX_TEXT} characters`),
    isin: isinText,
    issuer: requiredText,
    bond_type: bondTypeEnum,
    platform: optionalText,
    quantity: positiveInteger,
    face_value: z.number().nullable(),
    purchase_price: moneyNumber,
    invested_amount: moneyNumber,
    purchase_date: startDateString,
    ytm: rateNumber(30, YTM_ERROR),
    maturity_date: dateString,
    notes: notesText,
  })
  .superRefine((v, ctx) => {
    if (v.master_mode === "picker") {
      if (v.master_id === null) {
        ctx.addIssue({
          code: "custom",
          path: ["master_id"],
          message: BOND_REQUIRED_ERROR,
        });
      }
    } else if (v.name === "") {
      ctx.addIssue({ code: "custom", path: ["name"], message: "Required" });
    }
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
  )
  .refine((v) => maturityWithinLimit(v.purchase_date, v.maturity_date), {
    message: MATURITY_RANGE_ERROR,
    path: ["maturity_date"],
  })
  .refine(
    (v) => bondAmountsConsistent(v.quantity, v.purchase_price, v.invested_amount),
    {
      message: BOND_AMOUNT_MISMATCH_ERROR,
      path: ["invested_amount"],
    },
  );

type FormIn = z.input<typeof schema>;
type FormOut = z.output<typeof schema>;

const BOND_TYPE_OPTIONS = toOptions(BOND_TYPE_LABELS);

const FORM_TO_AMOUNT: Record<string, AmountField> = {
  quantity: "quantity",
  purchase_price: "price",
  invested_amount: "total",
};

function toNum(s: unknown): number | null {
  if (typeof s !== "string" || s.trim() === "") return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

const LINK_BUTTON =
  "w-fit text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline";

function metaLine(s: BondMaster): string {
  const parts: string[] = [s.isin];
  parts.push(BOND_TYPE_LABELS[s.bond_type] ?? s.bond_type);
  if (s.coupon_rate != null) parts.push(`${s.coupon_rate}%`);
  if (s.maturity_date) parts.push(`matures ${formatDate(s.maturity_date)}`);
  if (s.rating) {
    const uniq = Array.from(
      new Set(
        s.rating
          .split(",")
          .map((r) => r.trim())
          .filter(Boolean),
      ),
    );
    if (uniq.length) parts.push(uniq.join(", "));
  }
  return parts.filter(Boolean).join(" · ");
}

function toDefaults(r?: Bond): FormIn {
  return {
    master_mode: !r || r.master_id != null ? "picker" : "manual",
    master_id: r?.master_id ?? null,
    name: r?.name ?? "",
    isin: r?.isin ?? "",
    issuer: r?.issuer ?? "",
    bond_type: r?.bond_type ?? "government",
    platform: r?.platform ?? "",
    quantity: r ? String(r.quantity) : "",
    face_value: r?.face_value ?? null,
    purchase_price: r ? String(r.purchase_price) : "",
    invested_amount: r ? String(r.invested_amount) : "",
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
  const {
    control,
    handleSubmit,
    setValue,
    getValues,
    setError,
    clearErrors,
    trigger,
    getFieldState,
    formState,
  } = useForm<FormIn, unknown, FormOut>({
    resolver: zodResolver(schema),
    defaultValues: toDefaults(record),
  });
  const { saving, save } = useAssetSave("bond", record, onSaved, (issues) => {
    for (const i of issues) {
      if (i.field === "master_id") {
        setError("master_id", { type: "server", message: i.message });
      }
    }
  });
  const mode = useWatch({ control, name: "master_mode" });
  const bondName = useWatch({ control, name: "name" });
  const purchaseDate = useWatch({ control, name: "purchase_date" });
  const maturityLimit = isValidISODate(purchaseDate)
    ? addMonthsISO(purchaseDate, MAX_BOND_YEARS * 12)
    : undefined;
  const qtyStr = useWatch({ control, name: "quantity" });
  const priceStr = useWatch({ control, name: "purchase_price" });
  const totalStr = useWatch({ control, name: "invested_amount" });
  // The two amounts the user edited most recently (oldest first).
  const edited = useRef<AmountField[]>(
    record ? ["quantity", "price"] : [],
  );
  const lastKey = useRef(`${qtyStr}|${priceStr}|${totalStr}`);

  function markEdited(field: AmountField) {
    edited.current = [
      ...edited.current.filter((f) => f !== field),
      field,
    ].slice(-2);
  }

  useEffect(() => {
    const key = `${qtyStr}|${priceStr}|${totalStr}`;
    if (key === lastKey.current) return;
    lastKey.current = key;
    const d = deriveAmount(
      { quantity: toNum(qtyStr), price: toNum(priceStr), total: toNum(totalStr) },
      edited.current,
      BOND_PRECISION,
    );
    if (!d) return;
    const name =
      d.field === "quantity"
        ? "quantity"
        : d.field === "price"
          ? "purchase_price"
          : "invested_amount";
    const next = String(d.value);
    if (getValues(name) === next) return;
    lastKey.current = `${
      name === "quantity" ? next : qtyStr
    }|${name === "purchase_price" ? next : priceStr}|${
      name === "invested_amount" ? next : totalStr
    }`;
    const amountFields = ["quantity", "purchase_price", "invested_amount"] as const;
    const revalidate =
      formState.isSubmitted ||
      amountFields.some((f) => getFieldState(f, formState).error);
    setValue(name, next, { shouldDirty: true });
    if (revalidate) void trigger(amountFields);
  }, [
    qtyStr,
    priceStr,
    totalStr,
    getValues,
    setValue,
    trigger,
    getFieldState,
    formState,
  ]);

  // Master details for the summary line (selected, or fetched when editing).
  const [meta, setMeta] = useState<BondMaster | null>(null);

  const initialId = record?.master_id ?? null;
  useEffect(() => {
    if (initialId === null) return;
    let cancelled = false;
    apiGet<BondMaster>(`/master/bond/${initialId}`)
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

  function switchMode(next: "picker" | "manual") {
    setValue("master_mode", next);
    setValue("master_id", null);
    setMeta(null);
    clearErrors(["master_id", "name"]);
  }

  const onSubmit = handleSubmit((values) => {
    const manual = values.master_mode === "manual";
    const payload: BondInput = {
      master_id: manual ? null : values.master_id,
      name: values.name,
      isin: values.isin,
      issuer: values.issuer,
      bond_type: values.bond_type,
      platform: values.platform,
      quantity: values.quantity,
      face_value: values.face_value,
      purchase_price: values.purchase_price,
      invested_amount: values.invested_amount,
      purchase_date: values.purchase_date,
      ytm: values.ytm,
      maturity_date: values.maturity_date,
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
            name="master_id"
            render={({ field, fieldState }) => (
              <Field data-invalid={fieldState.invalid} className="gap-1.5">
                <FieldLabel
                  htmlFor="master_id"
                  className="text-xs font-normal text-muted-foreground"
                >
                  Bond
                </FieldLabel>
                <MasterPicker<BondMaster>
                  id="master_id"
                  hasValue={field.value !== null}
                  summary={
                    <>
                      <div className="truncate text-sm font-medium">
                        {meta?.name ?? bondName}
                      </div>
                      {meta ? (
                        <div className="truncate text-[11px] text-muted-foreground">
                          {metaLine(meta)}
                        </div>
                      ) : null}
                    </>
                  }
                  searchPath={(q) =>
                    `/master/bond?q=${encodeURIComponent(q)}&limit=20`
                  }
                  itemKey={(s) => s.id}
                  itemLabel={(s) => s.name}
                  renderItem={(s) => (
                    <>
                      <span className="truncate text-sm">{s.name}</span>
                      <span className="truncate text-[11px] text-muted-foreground">
                        {metaLine(s)}
                      </span>
                    </>
                  )}
                  placeholder="Search bonds…"
                  emptyLabel="No matching bonds"
                  invalid={fieldState.invalid}
                  onBlur={field.onBlur}
                  onSelect={(s) => {
                    setMeta(s);
                    field.onChange(s.id);
                    setValue("name", s.name);
                    setValue("isin", s.isin);
                    if (s.issuer) setValue("issuer", s.issuer);
                    setValue("bond_type", s.bond_type);
                    setValue("face_value", s.face_value);
                    if (s.maturity_date) {
                      setValue("maturity_date", s.maturity_date);
                    }
                    if (
                      s.issue_date &&
                      s.issue_date <= todayISO() &&
                      !getValues("purchase_date")
                    ) {
                      setValue("purchase_date", s.issue_date);
                    }
                  }}
                />
                <FormError error={fieldState.error} />
              </Field>
            )}
          />
        ) : (
          <TextField control={control} name="name" label="Bond name" required />
        )}
        <button
          type="button"
          className={LINK_BUTTON}
          onClick={() => switchMode(mode === "picker" ? "manual" : "picker")}
        >
          {mode === "picker"
            ? "Not listed? Enter manually"
            : "Search the bond list instead"}
        </button>
      </div>
      <TextField
        control={control}
        name="isin"
        label="ISIN"
        maxLength={MAX_ISIN}
        uppercase
      />
      <TextField control={control} name="issuer" label="Issuer" required />
      <SelectField
        control={control}
        name="bond_type"
        label="Bond type"
        options={BOND_TYPE_OPTIONS}
        required
      />
      <TextField control={control} name="platform" label="Platform" />
      <div
        className="contents"
        onInputCapture={(e) => {
          const f = FORM_TO_AMOUNT[(e.target as HTMLInputElement).name];
          if (f) markEdited(f);
        }}
      >
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
          name="purchase_price"
          label="Purchase price per unit"
          adornment="₹"
          inputMode="decimal"
          decimals={2}
          required
        />
        <TextField
          control={control}
          name="invested_amount"
          label="Total invested"
          adornment="₹"
          inputMode="decimal"
          decimals={2}
          required
        />
      </div>
      <DateField
        control={control}
        name="purchase_date"
        label="Purchase date"
        maxDate={maxFutureDateISO()}
        required
      />
      <TextField
        control={control}
        name="ytm"
        label="Yield to maturity p.a."
        adornment="%"
        inputMode="decimal"
        decimals={2}
        required
      />
      <DateField
        control={control}
        name="maturity_date"
        label="Maturity date"
        maxDate={maturityLimit}
        toYear={maturityLimit ? Number(maturityLimit.slice(0, 4)) : undefined}
        required
      />
      <div className="sm:col-span-2">
        <NotesField control={control} name="notes" />
      </div>
    </FormShell>
  );
}

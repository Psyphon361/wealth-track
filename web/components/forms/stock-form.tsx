"use client";

import { useEffect, useRef, useState } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { apiGet } from "@/lib/api";
import {
  EXCHANGE_LABELS,
  type Exchange,
  type Security,
  type Stock,
  type StockInput,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
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
  MAX_SYMBOL,
  MAX_TEXT,
  STOCK_REQUIRED_ERROR,
  exchangeEnum,
  maxFutureDateISO,
  moneyNumber,
  notesText,
  optionalText,
  positiveInteger,
  startDateString,
  symbolText,
} from "./schema";
import { useAssetSave } from "./use-asset-form";

const schema = z
  .object({
    security_mode: z.enum(["picker", "manual"]),
    security_id: z.number().nullable(),
    name: z
      .string()
      .trim()
      .max(MAX_TEXT, `Must be at most ${MAX_TEXT} characters`),
    symbol: symbolText,
    exchange: exchangeEnum,
    broker: optionalText,
    quantity: positiveInteger,
    avg_buy_price: moneyNumber,
    buy_date: startDateString,
    notes: notesText,
  })
  .superRefine((v, ctx) => {
    if (v.security_mode === "picker") {
      if (v.security_id === null) {
        ctx.addIssue({
          code: "custom",
          path: ["security_id"],
          message: STOCK_REQUIRED_ERROR,
        });
      }
    } else if (v.name === "") {
      ctx.addIssue({ code: "custom", path: ["name"], message: "Required" });
    }
  });

type FormIn = z.input<typeof schema>;
type FormOut = z.output<typeof schema>;

const EXCHANGE_OPTIONS = toOptions(EXCHANGE_LABELS);

const LINK_BUTTON =
  "w-fit text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline";

function symbolFor(s: Security, exchange: Exchange): string {
  if (exchange === "NSE" && s.nse_symbol) return s.nse_symbol;
  return s.bse_symbol ?? s.bse_code ?? s.nse_symbol ?? "";
}

function codesLine(s: Security): string {
  const parts: string[] = [];
  if (s.nse_symbol) parts.push(`NSE: ${s.nse_symbol}`);
  const bse = s.bse_symbol ?? s.bse_code;
  if (bse) parts.push(`BSE: ${bse}`);
  parts.push(s.isin);
  return parts.join(" · ");
}

function toDefaults(r?: Stock): FormIn {
  return {
    security_mode: !r || r.security_id != null ? "picker" : "manual",
    security_id: r?.security_id ?? null,
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
  const { control, handleSubmit, setValue, setError, clearErrors } = useForm<
    FormIn,
    unknown,
    FormOut
  >({
    resolver: zodResolver(schema),
    defaultValues: toDefaults(record),
  });
  const { saving, save } = useAssetSave("stock", record, onSaved, (issues) => {
    for (const i of issues) {
      if (i.field === "security_id") {
        setError("security_id", { type: "server", message: i.message });
      }
    }
  });
  const mode = useWatch({ control, name: "security_mode" });
  const securityName = useWatch({ control, name: "name" });
  const exchange = useWatch({ control, name: "exchange" });
  // Master details for the summary line (selected, or fetched when editing).
  const [meta, setMeta] = useState<Security | null>(null);
  const metaRef = useRef<Security | null>(null);

  function updateMeta(s: Security | null) {
    metaRef.current = s;
    setMeta(s);
  }

  const initialId = record?.security_id ?? null;
  useEffect(() => {
    if (initialId === null) return;
    let cancelled = false;
    apiGet<Security>(`/master/security/${initialId}`)
      .then((s) => {
        if (!cancelled) updateMeta(s);
      })
      .catch(() => {
        // 404 or network: keep showing the stored name.
      });
    return () => {
      cancelled = true;
    };
  }, [initialId]);

  // Switching exchange re-derives the symbol from the picked security.
  const lastExchange = useRef(exchange);
  useEffect(() => {
    if (lastExchange.current === exchange) return;
    lastExchange.current = exchange;
    const s = metaRef.current;
    if (s) setValue("symbol", symbolFor(s, exchange));
  }, [exchange, setValue]);

  function switchMode(next: "picker" | "manual") {
    setValue("security_mode", next);
    setValue("security_id", null);
    updateMeta(null);
    clearErrors(["security_id", "name"]);
  }

  const onSubmit = handleSubmit((values) => {
    const manual = values.security_mode === "manual";
    const payload: StockInput = {
      security_id: manual ? null : values.security_id,
      name: values.name,
      symbol: values.symbol,
      exchange: values.exchange,
      broker: values.broker,
      quantity: values.quantity,
      avg_buy_price: values.avg_buy_price,
      buy_date: values.buy_date,
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
            name="security_id"
            render={({ field, fieldState }) => (
              <Field data-invalid={fieldState.invalid} className="gap-1.5">
                <FieldLabel
                  htmlFor="security_id"
                  className="text-xs font-normal text-muted-foreground"
                >
                  Stock
                </FieldLabel>
                <MasterPicker<Security>
                  id="security_id"
                  hasValue={field.value !== null}
                  summary={
                    <>
                      <div className="truncate text-sm font-medium">
                        {meta?.name ?? securityName}
                      </div>
                      {meta ? (
                        <div className="truncate text-[11px] text-muted-foreground">
                          {codesLine(meta)}
                        </div>
                      ) : null}
                    </>
                  }
                  searchPath={(q) =>
                    `/master/stock?q=${encodeURIComponent(q)}&limit=20`
                  }
                  itemKey={(s) => s.id}
                  itemLabel={(s) => s.name}
                  renderItem={(s) => (
                    <>
                      <span className="flex items-center gap-2">
                        <span className="min-w-0 truncate text-sm">
                          {s.name}
                        </span>
                        {s.kind === "etf" ? (
                          <Badge variant="secondary" className="h-4 px-1.5 text-[10px]">
                            ETF
                          </Badge>
                        ) : null}
                      </span>
                      <span className="truncate text-[11px] text-muted-foreground">
                        {codesLine(s)}
                      </span>
                    </>
                  )}
                  placeholder="Search stocks and ETFs…"
                  emptyLabel="No matching stocks"
                  invalid={fieldState.invalid}
                  onBlur={field.onBlur}
                  onSelect={(s) => {
                    const ex: Exchange = s.nse_symbol ? "NSE" : "BSE";
                    updateMeta(s);
                    lastExchange.current = ex;
                    field.onChange(s.id);
                    setValue("name", s.name);
                    setValue("exchange", ex);
                    setValue("symbol", symbolFor(s, ex));
                  }}
                />
                <FormError error={fieldState.error} />
              </Field>
            )}
          />
        ) : (
          <TextField
            control={control}
            name="name"
            label="Company name"
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
            : "Search the stock list instead"}
        </button>
      </div>
      <TextField
        control={control}
        name="symbol"
        label="Symbol"
        maxLength={MAX_SYMBOL}
        uppercase
      />
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
        decimals={0}
        required
      />
      <TextField
        control={control}
        name="avg_buy_price"
        label="Average buy price"
        adornment="₹"
        inputMode="decimal"
        decimals={2}
        required
      />
      <DateField
        control={control}
        name="buy_date"
        label="Buy date"
        maxDate={maxFutureDateISO()}
        required
      />
      <div className="sm:col-span-2">
        <NotesField control={control} name="notes" />
      </div>
    </FormShell>
  );
}

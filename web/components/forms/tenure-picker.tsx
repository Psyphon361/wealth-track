"use client";

import {
  Controller,
  useFormState,
  type Control,
  type FieldValues,
  type Path,
} from "react-hook-form";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type TenureNames<TIn extends FieldValues> = {
  years: Path<TIn>;
  months: Path<TIn>;
  days: Path<TIn>;
};

function range(max: number) {
  return Array.from({ length: max + 1 }, (_, i) => ({
    value: String(i),
    label: String(i),
  }));
}

const UNITS = [
  { key: "years", label: "Years", max: 30 },
  { key: "months", label: "Months", max: 11 },
  { key: "days", label: "Days", max: 30 },
] as const;

export function TenurePicker<TIn extends FieldValues, TOut>({
  control,
  names,
}: {
  control: Control<TIn, unknown, TOut>;
  names: TenureNames<TIn>;
}) {
  const { errors } = useFormState({ control });
  const messages = [names.years, names.months, names.days].map((n) => {
    const e = (errors as Record<string, { message?: unknown } | undefined>)[n];
    return typeof e?.message === "string" ? { message: e.message } : undefined;
  });

  return (
    <Field data-invalid={messages.some(Boolean)}>
      <FieldLabel className="text-xs font-normal text-muted-foreground">
        Tenure
      </FieldLabel>
      <div className="grid grid-cols-3 gap-3">
        {UNITS.map((u) => {
          const name = names[u.key];
          const options = range(u.max);
          return (
            <Controller
              key={u.key}
              control={control}
              name={name}
              render={({ field }) => (
                <div className="flex flex-col gap-1">
                  <Select
                    items={options}
                    value={String(field.value ?? "0")}
                    onValueChange={(v) => field.onChange(v ?? "0")}
                  >
                    <SelectTrigger
                      className="num w-full"
                      aria-label={u.label}
                      onBlur={field.onBlur}
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {options.map((o) => (
                        <SelectItem key={o.value} value={o.value}>
                          {o.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <span className="text-[11px] text-muted-foreground/70">
                    {u.label}
                  </span>
                </div>
              )}
            />
          );
        })}
      </div>
      <FieldError errors={messages} className="text-xs text-destructive" />
    </Field>
  );
}

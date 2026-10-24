"use client";

import { useImperativeHandle, useLayoutEffect, useRef, useState } from "react";
import {
  caretAfterChars,
  formatIndianNumber,
  sanitizeNumber,
} from "./number-format";
import {
  Controller,
  type Control,
  type FieldValues,
  type Path,
} from "react-hook-form";
import { cn } from "cn";
import { CalendarDays } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { formatDate } from "@/lib/format";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export type Option = { value: string; label: string };

export function toOptions<K extends string>(
  labels: Record<K, string>,
): Option[] {
  return (Object.keys(labels) as K[]).map((value) => ({
    value,
    label: labels[value],
  }));
}

interface FieldProps<TIn extends FieldValues, TOut> {
  control: Control<TIn, unknown, TOut>;
  name: Path<TIn>;
  label: string;
  required?: boolean;
}

function Label({
  id,
  label,
  required,
}: {
  id: string;
  label: string;
  required?: boolean;
}) {
  return (
    <FieldLabel
      htmlFor={id}
      className="text-xs font-normal text-muted-foreground"
    >
      {label}
      {required ? null : (
        <span className="text-[10px] tracking-wide text-muted-foreground/60 uppercase">
          optional
        </span>
      )}
    </FieldLabel>
  );
}

export function FormError({
  error,
}: {
  error: { message?: string } | undefined;
}) {
  return <FieldError errors={[error]} className="text-xs text-destructive" />;
}

interface GroupedInputProps extends Omit<
  React.ComponentProps<typeof Input>,
  "value" | "onChange" | "type"
> {
  value: string;
  onValueChange: (raw: string) => void;
  decimals: number;
}

/** Text input showing Indian digit grouping; reports the plain number string. */
function GroupedInput({
  value,
  onValueChange,
  decimals,
  onKeyDown,
  ref,
  ...props
}: GroupedInputProps) {
  const innerRef = useRef<HTMLInputElement | null>(null);
  const caret = useRef<number | null>(null);
  const display = formatIndianNumber(sanitizeNumber(value, decimals));

  useLayoutEffect(() => {
    const el = innerRef.current;
    if (el && caret.current !== null && document.activeElement === el) {
      el.setSelectionRange(caret.current, caret.current);
    }
    caret.current = null;
  });

  useImperativeHandle(ref, () => innerRef.current as HTMLInputElement);

  return (
    <Input
      {...props}
      ref={innerRef}
      value={display}
      onKeyDown={(e) => {
        onKeyDown?.(e);
        const el = e.currentTarget;
        const pos = el.selectionStart;
        if (pos === null || pos !== el.selectionEnd) return;
        // Skip over a comma so Backspace/Delete removes the adjacent digit.
        if (e.key === "Backspace" && el.value[pos - 1] === ",") {
          el.setSelectionRange(pos - 1, pos - 1);
        } else if (e.key === "Delete" && el.value[pos] === ",") {
          el.setSelectionRange(pos + 1, pos + 1);
        }
      }}
      onChange={(e) => {
        const typed = e.target.value;
        const pos = e.target.selectionStart ?? typed.length;
        const kept = sanitizeNumber(typed.slice(0, pos), decimals).length;
        const raw = sanitizeNumber(typed, decimals);
        caret.current = caretAfterChars(
          formatIndianNumber(raw),
          Math.min(kept, raw.length),
        );
        onValueChange(raw);
      }}
    />
  );
}

export function TextField<TIn extends FieldValues, TOut>({
  control,
  name,
  label,
  required,
  inputMode,
  adornment,
  decimals,
}: FieldProps<TIn, TOut> & {
  inputMode?: "decimal" | "numeric";
  adornment?: "₹" | "%";
  /** When set, groups digits Indian-style, allowing this many decimal places. */
  decimals?: number;
}) {
  const numeric = inputMode !== undefined;
  return (
    <Controller
      control={control}
      name={name}
      render={({ field, fieldState }) => (
        <Field data-invalid={fieldState.invalid}>
          <Label id={name} label={label} required={required} />
          <div className="relative">
            {decimals !== undefined ? (
              <GroupedInput
                id={name}
                inputMode={inputMode}
                name={field.name}
                ref={field.ref}
                onBlur={field.onBlur}
                onValueChange={field.onChange}
                value={String(field.value ?? "")}
                decimals={decimals}
                aria-invalid={fieldState.invalid}
                className={cn(
                  "num text-right",
                  adornment === "₹" && "pl-6",
                  adornment === "%" && "pr-6",
                )}
              />
            ) : (
              <Input
                id={name}
                inputMode={inputMode}
                name={field.name}
                ref={field.ref}
                onBlur={field.onBlur}
                onChange={field.onChange}
                value={String(field.value ?? "")}
                aria-invalid={fieldState.invalid}
                className={cn(
                  numeric && "num text-right",
                  adornment === "₹" && "pl-6",
                  adornment === "%" && "pr-6",
                )}
              />
            )}
            {adornment ? (
              <span
                aria-hidden
                className={cn(
                  "pointer-events-none absolute top-1/2 -translate-y-1/2 text-xs text-muted-foreground",
                  adornment === "₹" ? "left-2.5" : "right-2.5",
                )}
              >
                {adornment}
              </span>
            ) : null}
          </div>
          <FormError error={fieldState.error} />
        </Field>
      )}
    />
  );
}

export function SelectField<TIn extends FieldValues, TOut>({
  control,
  name,
  label,
  required,
  options,
}: FieldProps<TIn, TOut> & { options: Option[] }) {
  return (
    <Controller
      control={control}
      name={name}
      render={({ field, fieldState }) => (
        <Field data-invalid={fieldState.invalid}>
          <Label id={name} label={label} required={required} />
          <Select
            items={options}
            value={String(field.value ?? "")}
            onValueChange={(v) => field.onChange(v ?? "")}
          >
            <SelectTrigger
              id={name}
              className="w-full"
              aria-invalid={fieldState.invalid}
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
          <FormError error={fieldState.error} />
        </Field>
      )}
    />
  );
}

export function NotesField<TIn extends FieldValues, TOut>({
  control,
  name,
}: Pick<FieldProps<TIn, TOut>, "control" | "name">) {
  return (
    <Controller
      control={control}
      name={name}
      render={({ field, fieldState }) => (
        <Field data-invalid={fieldState.invalid}>
          <Label id={name} label="Notes" />
          <Textarea
            id={name}
            name={field.name}
            ref={field.ref}
            onBlur={field.onBlur}
            onChange={field.onChange}
            value={String(field.value ?? "")}
            aria-invalid={fieldState.invalid}
            rows={2}
          />
          <FormError error={fieldState.error} />
        </Field>
      )}
    />
  );
}

const pad = (n: number) => String(n).padStart(2, "0");

function parseISODate(value: string): Date | undefined {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!m) return undefined;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
}

function toISODate(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

const DATE_START_YEAR = 1990;

export function DateField<TIn extends FieldValues, TOut>({
  control,
  name,
  label,
  required,
}: FieldProps<TIn, TOut>) {
  const [open, setOpen] = useState(false);
  const endYear = new Date().getFullYear() + 40;
  return (
    <Controller
      control={control}
      name={name}
      render={({ field, fieldState }) => {
        const value = String(field.value ?? "");
        const selected = parseISODate(value);
        return (
          <Field data-invalid={fieldState.invalid}>
            <Label id={name} label={label} required={required} />
            <Popover open={open} onOpenChange={setOpen}>
              <PopoverTrigger
                render={
                  <Button
                    id={name}
                    ref={field.ref}
                    type="button"
                    variant="outline"
                    aria-invalid={fieldState.invalid}
                    onBlur={field.onBlur}
                    className="h-8 w-full justify-start rounded-lg px-2.5 font-normal aria-invalid:border-destructive"
                  />
                }
              >
                <CalendarDays className="size-4 text-muted-foreground" />
                {selected ? (
                  <span className="num">{formatDate(value)}</span>
                ) : (
                  <span className="text-muted-foreground">Pick a date</span>
                )}
              </PopoverTrigger>
              <PopoverContent align="start" className="w-auto p-0">
                <Calendar
                  mode="single"
                  captionLayout="dropdown"
                  weekStartsOn={1}
                  startMonth={new Date(DATE_START_YEAR, 0)}
                  endMonth={new Date(endYear, 11)}
                  defaultMonth={selected}
                  selected={selected}
                  onSelect={(d) => {
                    if (d) field.onChange(toISODate(d));
                    setOpen(false);
                  }}
                />
              </PopoverContent>
            </Popover>
            <FormError error={fieldState.error} />
          </Field>
        );
      }}
    />
  );
}

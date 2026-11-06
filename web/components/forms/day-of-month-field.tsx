"use client";

import { useRef, useState } from "react";
import {
  Controller,
  type Control,
  type FieldValues,
  type Path,
} from "react-hook-form";
import { cn } from "cn";
import { CalendarDays } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ordinal } from "@/lib/sip";
import { FormError, Label } from "./fields";
import { useFormDisabled } from "./form-disabled";

const DAYS = Array.from({ length: 28 }, (_, i) => i + 1);
const COLUMNS = 7;

/** Day of the month shown on the trigger: "5th of every month". */
export function dayTriggerText(day: number): string {
  return `${ordinal(day)} of every month`;
}

function DayGrid({
  selected,
  onPick,
}: {
  selected: number | null;
  onPick: (day: number) => void;
}) {
  const today = new Date().getDate();
  const [active, setActive] = useState(selected ?? 1);
  const refs = useRef<Map<number, HTMLButtonElement>>(new Map());

  function move(to: number) {
    const next = Math.min(28, Math.max(1, to));
    setActive(next);
    refs.current.get(next)?.focus();
  }

  function onKeyDown(e: React.KeyboardEvent, day: number) {
    const steps: Record<string, number> = {
      ArrowLeft: -1,
      ArrowRight: 1,
      ArrowUp: -COLUMNS,
      ArrowDown: COLUMNS,
    };
    const step = steps[e.key];
    if (step === undefined) return;
    e.preventDefault();
    move(day + step);
  }

  return (
    <div
      role="group"
      aria-label="Day of the month"
      className="grid grid-cols-7 gap-0.5"
    >
      {DAYS.map((day) => {
        const isSelected = day === selected;
        return (
          <button
            key={day}
            type="button"
            ref={(el) => {
              if (el) refs.current.set(day, el);
              else refs.current.delete(day);
            }}
            tabIndex={day === active ? 0 : -1}
            aria-pressed={isSelected}
            aria-label={`${ordinal(day)} of every month`}
            onClick={() => onPick(day)}
            onFocus={() => setActive(day)}
            onKeyDown={(e) => onKeyDown(e, day)}
            className={cn(
              "num flex h-9 items-center justify-center rounded-md text-[13.5px] transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
              isSelected
                ? "bg-primary text-primary-foreground"
                : "hover:bg-muted",
              day === today && !isSelected && "ring-1 ring-inset ring-foreground/30",
            )}
          >
            {day}
          </button>
        );
      })}
    </div>
  );
}

/** Compact day-of-month picker (1 to 28): a trigger opening a 7-column day grid. */
export function DayOfMonthField<TIn extends FieldValues, TOut>({
  control,
  name,
  label = "SIP date",
  required,
}: {
  control: Control<TIn, unknown, TOut>;
  name: Path<TIn>;
  label?: string;
  required?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const locked = useFormDisabled();
  return (
    <Controller
      control={control}
      name={name}
      render={({ field, fieldState }) => {
        const day = Number(field.value);
        const has = Number.isInteger(day) && day >= 1 && day <= 28;
        return (
          <Field data-invalid={fieldState.invalid} className="gap-1.5">
            <Label id={name} label={label} required={required} />
            <Popover open={open && !locked} onOpenChange={setOpen}>
              <PopoverTrigger
                render={
                  <Button
                    id={name}
                    ref={field.ref}
                    type="button"
                    variant="outline"
                    disabled={locked}
                    aria-invalid={fieldState.invalid}
                    aria-describedby={`${name}_help`}
                    onBlur={field.onBlur}
                    className="h-8 w-full justify-between rounded-lg px-2.5 font-normal aria-invalid:border-destructive"
                  />
                }
              >
                {has ? (
                  <span className="num">{dayTriggerText(day)}</span>
                ) : (
                  <span className="text-muted-foreground">Pick a day</span>
                )}
                <CalendarDays className="size-4 text-muted-foreground" />
              </PopoverTrigger>
              <PopoverContent
                align="start"
                className="w-[17.5rem] max-w-[calc(100vw-2rem)] gap-2 p-2"
              >
                <DayGrid
                  selected={has ? day : null}
                  onPick={(d) => {
                    field.onChange(String(d));
                    setOpen(false);
                  }}
                />
                <p className="px-0.5 text-[11px] text-muted-foreground">
                  Days 29–31 aren&apos;t offered so every month has the date.
                </p>
              </PopoverContent>
            </Popover>
            <p id={`${name}_help`} className="text-[11px] text-muted-foreground">
              Instalments are bought on this day each month; a holiday moves it
              to the next working day.
            </p>
            <FormError error={fieldState.error} />
          </Field>
        );
      }}
    />
  );
}

"use client";

import { useState } from "react";
import { CalendarDays, Percent } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { sanitizeNumber } from "@/components/forms/number-format";
import { formatDate } from "@/lib/format";

function RangeTrigger({
  icon,
  title,
  summary,
}: {
  icon: React.ReactNode;
  title: string;
  summary: string | null;
}) {
  return (
    <PopoverTrigger
      render={
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-8 border-dashed"
        />
      }
    >
      {icon}
      {title}
      {summary ? (
        <>
          <span className="mx-0.5 h-4 w-px bg-border" aria-hidden />
          <span className="num font-normal">{summary}</span>
        </>
      ) : null}
    </PopoverTrigger>
  );
}

function RangeActions({
  canApply,
  hasValue,
  onApply,
  onClear,
}: {
  canApply: boolean;
  hasValue: boolean;
  onApply: () => void;
  onClear: () => void;
}) {
  return (
    <div className="flex justify-between gap-2 pt-1">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        disabled={!hasValue}
        onClick={onClear}
      >
        Clear
      </Button>
      <Button type="button" size="sm" disabled={!canApply} onClick={onApply}>
        Apply
      </Button>
    </div>
  );
}

// ---- Percent range ----

function PercentInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (raw: string) => void;
}) {
  return (
    <label className="flex flex-1 flex-col gap-1 text-xs text-muted-foreground">
      {label}
      <div className="relative">
        <Input
          inputMode="decimal"
          placeholder="Any"
          value={value}
          onChange={(e) => onChange(sanitizeNumber(e.target.value, 2))}
          className="num pr-6 text-right"
        />
        <span
          aria-hidden
          className="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2 text-xs text-muted-foreground"
        >
          %
        </span>
      </div>
    </label>
  );
}

function PercentForm({
  min,
  max,
  onApply,
}: {
  min: string;
  max: string;
  onApply: (min: string, max: string) => void;
}) {
  const [lo, setLo] = useState(min);
  const [hi, setHi] = useState(max);
  const inverted = lo !== "" && hi !== "" && Number(lo) > Number(hi);
  return (
    <>
      <div className="flex gap-2">
        <PercentInput label="Min" value={lo} onChange={setLo} />
        <PercentInput label="Max" value={hi} onChange={setHi} />
      </div>
      <RangeActions
        canApply={!inverted}
        hasValue={min !== "" || max !== "" || lo !== "" || hi !== ""}
        onApply={() => onApply(lo, hi)}
        onClear={() => onApply("", "")}
      />
    </>
  );
}

export function PercentRangeFilter({
  title,
  min,
  max,
  onChange,
}: {
  title: string;
  min: string;
  max: string;
  onChange: (min: string, max: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const summary =
    min && max
      ? `${min}% – ${max}%`
      : min
        ? `≥ ${min}%`
        : max
          ? `≤ ${max}%`
          : null;
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <RangeTrigger
        icon={<Percent className="size-3.5" aria-hidden />}
        title={title}
        summary={summary}
      />
      <PopoverContent align="start" className="w-64">
        <PercentForm
          min={min}
          max={max}
          onApply={(lo, hi) => {
            onChange(lo, hi);
            setOpen(false);
          }}
        />
      </PopoverContent>
    </Popover>
  );
}

// ---- Date range ----

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

function DatePick({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (iso: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const selected = parseISODate(value);
  const endYear = new Date().getFullYear() + 40;
  return (
    <div className="flex flex-1 flex-col gap-1 text-xs text-muted-foreground">
      {label}
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger
          render={
            <Button
              type="button"
              variant="outline"
              className="h-8 w-full justify-start rounded-lg px-2.5 font-normal"
            />
          }
        >
          <CalendarDays className="size-4 text-muted-foreground" />
          {selected ? (
            <span className="num text-foreground">{formatDate(value)}</span>
          ) : (
            <span className="text-muted-foreground">Any</span>
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
              if (d) onChange(toISODate(d));
              setOpen(false);
            }}
          />
        </PopoverContent>
      </Popover>
    </div>
  );
}

function DateRangeForm({
  from,
  to,
  onApply,
}: {
  from: string;
  to: string;
  onApply: (from: string, to: string) => void;
}) {
  const [a, setA] = useState(from);
  const [b, setB] = useState(to);
  const inverted = a !== "" && b !== "" && a > b;
  return (
    <>
      <div className="flex flex-col gap-2 sm:flex-row">
        <DatePick label="From" value={a} onChange={setA} />
        <DatePick label="To" value={b} onChange={setB} />
      </div>
      <RangeActions
        canApply={!inverted}
        hasValue={from !== "" || to !== "" || a !== "" || b !== ""}
        onApply={() => onApply(a, b)}
        onClear={() => onApply("", "")}
      />
    </>
  );
}

export function DateRangeFilter({
  title,
  from,
  to,
  onChange,
}: {
  title: string;
  from: string;
  to: string;
  onChange: (from: string, to: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const summary =
    from && to
      ? `${formatDate(from)} – ${formatDate(to)}`
      : from
        ? `from ${formatDate(from)}`
        : to
          ? `until ${formatDate(to)}`
          : null;
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <RangeTrigger
        icon={<CalendarDays className="size-3.5" aria-hidden />}
        title={title}
        summary={summary}
      />
      <PopoverContent align="start" className="w-72 sm:w-80">
        <DateRangeForm
          from={from}
          to={to}
          onApply={(f, t) => {
            onChange(f, t);
            setOpen(false);
          }}
        />
      </PopoverContent>
    </Popover>
  );
}

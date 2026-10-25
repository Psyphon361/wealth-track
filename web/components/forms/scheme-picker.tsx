"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "cn";
import { ChevronsUpDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { apiGet, toApiMessage } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { MfOption, MfPlan, MfScheme } from "@/lib/types";

export type SchemeValue = { scheme_code: number; name: string } | null;

const PLAN_LABELS: Record<MfPlan, string> = {
  direct: "Direct",
  regular: "Regular",
};

const OPTION_LABELS: Record<MfOption, string> = {
  growth: "Growth",
  idcw: "IDCW",
  bonus: "Bonus",
  other: "Other",
};

const FREQUENCY_LABELS: Record<string, string> = {
  daily: "Daily",
  weekly: "Weekly",
  monthly: "Monthly",
  quarterly: "Quarterly",
  half_yearly: "Half-yearly",
  annual: "Annual",
};

const MIN_QUERY = 2;
const DEBOUNCE_MS = 250;

type SchemeMeta = Pick<
  MfScheme,
  "amc" | "plan" | "option" | "idcw_frequency"
>;

function metaLine(s: SchemeMeta): string {
  const parts: string[] = [s.amc];
  if (s.plan) parts.push(PLAN_LABELS[s.plan] ?? s.plan);
  if (s.option) {
    let opt = OPTION_LABELS[s.option] ?? s.option;
    if (s.idcw_frequency) {
      opt += ` · ${FREQUENCY_LABELS[s.idcw_frequency] ?? s.idcw_frequency}`;
    }
    parts.push(opt);
  }
  return parts.filter(Boolean).join(" · ");
}

const nav4 = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
});

export function SchemePicker({
  id,
  value,
  scheme,
  onSelect,
  onBlur,
  invalid,
}: {
  id?: string;
  value: SchemeValue;
  /** Master details for the current value (for the summary line), if known. */
  scheme?: SchemeMeta | null;
  onSelect: (scheme: MfScheme) => void;
  onBlur?: () => void;
  invalid?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<MfScheme[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
      requestId.current += 1;
    },
    [],
  );

  function handleQuery(next: string) {
    setQuery(next);
    if (timer.current) clearTimeout(timer.current);
    const q = next.trim();
    const rid = ++requestId.current;
    setError(null);
    if (q.length < MIN_QUERY) {
      setResults([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    timer.current = setTimeout(async () => {
      try {
        const data = await apiGet<MfScheme[]>(
          `/master/mf?q=${encodeURIComponent(q)}&limit=20`,
        );
        if (rid !== requestId.current) return;
        setResults(data);
      } catch (err) {
        if (rid !== requestId.current) return;
        setResults([]);
        setError(toApiMessage(err).message);
      } finally {
        if (rid === requestId.current) setLoading(false);
      }
    }, DEBOUNCE_MS);
  }

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      handleQuery("");
      onBlur?.();
    }
  }

  const trimmed = query.trim();
  const emptyText = error
    ? error
    : trimmed.length < MIN_QUERY
      ? "Type at least 2 characters"
      : loading
        ? "Searching…"
        : "No matching schemes";

  const trigger = value ? (
    <div
      id={id}
      className={cn(
        "flex min-h-8 w-full items-center gap-2 rounded-lg border border-input bg-input/30 px-2.5 py-1.5",
        invalid && "border-destructive",
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{value.name}</div>
        {scheme ? (
          <div className="truncate text-[11px] text-muted-foreground">
            {metaLine(scheme)}
          </div>
        ) : null}
      </div>
      <PopoverTrigger
        render={<Button type="button" variant="ghost" size="sm" />}
      >
        Change
      </PopoverTrigger>
    </div>
  ) : (
    <PopoverTrigger
      render={
        <Button
          id={id}
          type="button"
          variant="outline"
          aria-invalid={invalid}
          className="h-8 w-full justify-between rounded-lg px-2.5 font-normal aria-invalid:border-destructive"
        />
      }
    >
      <span className="truncate text-muted-foreground">
        Search mutual fund schemes…
      </span>
      <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" />
    </PopoverTrigger>
  );

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      {trigger}
      <PopoverContent align="start" className="w-[32rem] max-w-[90vw] p-0">
        <Command shouldFilter={false}>
          <CommandInput
            value={query}
            onValueChange={handleQuery}
            placeholder="Search mutual fund schemes…"
          />
          <CommandList>
            <CommandEmpty className="py-4 text-xs text-muted-foreground">
              {emptyText}
            </CommandEmpty>
            {results.length > 0 ? (
              <CommandGroup>
                {results.map((s) => (
                  <CommandItem
                    key={s.scheme_code}
                    value={String(s.scheme_code)}
                    aria-label={s.name}
                    onSelect={() => {
                      onSelect(s);
                      setOpen(false);
                      handleQuery("");
                    }}
                    className="w-full flex-col items-stretch gap-0.5 [&>svg]:hidden"
                  >
                    <span className="truncate text-sm">{s.name}</span>
                    <span className="flex items-baseline gap-2 text-[11px] text-muted-foreground">
                      <span className="min-w-0 flex-1 truncate">
                        {metaLine(s)}
                      </span>
                      {s.nav !== null && s.nav_date ? (
                        <span className="num shrink-0">
                          ₹{nav4.format(s.nav)} · {formatDate(s.nav_date)}
                        </span>
                      ) : null}
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
            ) : null}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

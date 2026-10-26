"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
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

const MIN_QUERY = 2;
const DEBOUNCE_MS = 250;

export function MasterPicker<T>({
  id,
  hasValue,
  summary,
  searchPath,
  itemKey,
  itemLabel,
  renderItem,
  placeholder,
  emptyLabel,
  onSelect,
  onBlur,
  invalid,
}: {
  id?: string;
  /** Whether a value is currently selected (shows the summary + Change). */
  hasValue: boolean;
  /** Content of the selected summary (title + optional meta line). */
  summary: ReactNode;
  /** Builds the search URL (relative to the API base) for a trimmed query. */
  searchPath: (q: string) => string;
  itemKey: (item: T) => string | number;
  itemLabel: (item: T) => string;
  renderItem: (item: T) => ReactNode;
  placeholder: string;
  /** Shown when a search returns nothing, e.g. "No matching schemes". */
  emptyLabel: string;
  onSelect: (item: T) => void;
  onBlur?: () => void;
  invalid?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<T[]>([]);
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
        const data = await apiGet<T[]>(searchPath(q));
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
        : emptyLabel;

  const trigger = hasValue ? (
    <div
      id={id}
      className={cn(
        "flex min-h-8 w-full items-center gap-2 rounded-lg border border-input bg-input/30 px-2.5 py-1.5",
        invalid && "border-destructive",
      )}
    >
      <div className="min-w-0 flex-1">{summary}</div>
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
      <span className="truncate text-muted-foreground">{placeholder}</span>
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
            placeholder={placeholder}
          />
          <CommandList>
            <CommandEmpty className="py-4 text-xs text-muted-foreground">
              {emptyText}
            </CommandEmpty>
            {results.length > 0 ? (
              <CommandGroup>
                {results.map((item) => (
                  <CommandItem
                    key={itemKey(item)}
                    value={String(itemKey(item))}
                    aria-label={itemLabel(item)}
                    onSelect={() => {
                      onSelect(item);
                      setOpen(false);
                      handleQuery("");
                    }}
                    className="w-full flex-col items-stretch gap-0.5 [&>svg]:hidden"
                  >
                    {renderItem(item)}
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

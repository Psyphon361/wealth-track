"use client";

import { ListFilter } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

export interface FacetOption<T extends string> {
  value: T;
  label: string;
  count?: number;
}

/**
 * Dashed-outline filter button opening a checkbox list. With `single`, picking
 * an option replaces the selection (and picking it again clears it).
 */
export function FacetedFilter<T extends string>({
  title,
  options,
  selected,
  onChange,
  single,
  searchable,
}: {
  title: string;
  options: FacetOption<T>[];
  selected: T[];
  onChange: (next: T[]) => void;
  single?: boolean;
  /** Show a search box above the options. */
  searchable?: boolean;
}) {
  function toggle(value: T) {
    const on = selected.includes(value);
    if (single) onChange(on ? [] : [value]);
    else onChange(on ? selected.filter((v) => v !== value) : [...selected, value]);
  }

  const chosen = options.filter((o) => selected.includes(o.value));

  return (
    <Popover>
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
        <ListFilter className="size-3.5" aria-hidden />
        {title}
        {chosen.length > 0 ? (
          <>
            <span className="mx-0.5 h-4 w-px bg-border" aria-hidden />
            {chosen.length > 2 ? (
              <Badge variant="secondary" className="px-1.5 font-normal">
                {chosen.length} selected
              </Badge>
            ) : (
              chosen.map((o) => (
                <Badge
                  key={o.value}
                  variant="secondary"
                  className="px-1.5 font-normal"
                >
                  {o.label}
                </Badge>
              ))
            )}
          </>
        ) : null}
      </PopoverTrigger>
      <PopoverContent align="start" className="w-52 p-0">
        <Command>
          {searchable ? (
            <CommandInput placeholder={`Search ${title.toLowerCase()}…`} />
          ) : null}
          <CommandList>
            {searchable ? <CommandEmpty>No matches.</CommandEmpty> : null}
            <CommandGroup>
              {options.map((o) => {
                const on = selected.includes(o.value);
                return (
                  <CommandItem
                    key={o.value}
                    value={o.label}
                    aria-label={o.label}
                    onSelect={() => toggle(o.value)}
                    className="w-full"
                  >
                    <Checkbox
                      checked={on}
                      tabIndex={-1}
                      aria-hidden
                      className="pointer-events-none"
                    />
                    <span className="truncate">{o.label}</span>
                    {o.count !== undefined ? (
                      <span className="num ml-auto text-xs text-muted-foreground">
                        {o.count}
                      </span>
                    ) : null}
                  </CommandItem>
                );
              })}
            </CommandGroup>
            {selected.length > 0 ? (
              <>
                <CommandSeparator />
                <CommandGroup>
                  <CommandItem
                    value="Clear filter"
                    aria-label="Clear filter"
                    onSelect={() => onChange([])}
                    className="justify-center"
                  >
                    Clear filter
                  </CommandItem>
                </CommandGroup>
              </>
            ) : null}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

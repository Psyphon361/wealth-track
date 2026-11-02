"use client";

import { useEffect, useRef, useState } from "react";
import {
  Controller,
  type Control,
  type FieldValues,
  type Path,
} from "react-hook-form";
import { cn } from "cn";
import { ChevronsUpDown, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Field } from "@/components/ui/field";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { apiGet } from "@/lib/api";
import { FormError, Label } from "./fields";
import { useFormDisabled } from "./form-disabled";

const FIXED_CATEGORIES = [
  "Crypto",
  "Real estate",
  "P2P lending",
  "Art & collectibles",
  "Unlisted shares",
];

/** The user's categories first, then the fixed list, de-duplicated ignoring case. */
function mergeCategories(mine: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const c of [...mine, ...FIXED_CATEGORIES]) {
    const key = c.trim().toLowerCase();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push(c);
  }
  return out;
}

/** Combobox with free entry: pick a suggestion or use whatever is typed. */
export function CategoryField<TIn extends FieldValues, TOut>({
  control,
  name,
  label,
  required,
}: {
  control: Control<TIn, unknown, TOut>;
  name: Path<TIn>;
  label: string;
  required?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const locked = useFormDisabled();
  const [query, setQuery] = useState("");
  const [mine, setMine] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const fieldRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    apiGet<string[]>("/master/other/categories")
      .then((data) => {
        if (!cancelled) setMine(data);
      })
      .catch(() => {
        // Suggestions are optional: the fixed list and free entry still work.
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const all = mergeCategories(mine);
  const typed = query.trim();
  const needle = typed.toLowerCase();
  const matches = all.filter((c) => c.toLowerCase().includes(needle));
  const exact = all.some((c) => c.toLowerCase() === needle);

  return (
    <Controller
      control={control}
      name={name}
      render={({ field, fieldState }) => {
        const value = String(field.value ?? "");
        function choose(next: string) {
          field.onChange(next);
          setOpen(false);
          setQuery("");
        }
        return (
          <Field data-invalid={fieldState.invalid} className="gap-1.5">
            <Label id={name} label={label} required={required} />
            <Popover
              open={open && !locked}
              onOpenChange={(next) => {
                setOpen(next);
                if (!next) {
                  setQuery("");
                  field.onBlur();
                }
              }}
            >
              <div ref={fieldRef} className="w-full">
                <PopoverTrigger
                  render={
                    <Button
                      id={name}
                      ref={field.ref}
                      type="button"
                      variant="outline"
                      disabled={locked}
                      aria-invalid={fieldState.invalid}
                      className="h-8 w-full justify-between rounded-lg px-2.5 font-normal aria-invalid:border-destructive"
                    />
                  }
                >
                  <span
                    className={cn(
                      "truncate",
                      !value && "text-muted-foreground",
                    )}
                  >
                    {value || "Choose or type a category"}
                  </span>
                  <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" />
                </PopoverTrigger>
              </div>
              <PopoverContent
                anchor={fieldRef}
                align="start"
                className="w-(--anchor-width) max-w-none p-0"
              >
                <Command shouldFilter={false}>
                  <CommandInput
                    value={query}
                    onValueChange={setQuery}
                    placeholder="Search or type a category"
                  />
                  <CommandList>
                    {loading ? (
                      <div className="flex items-center gap-2 px-2.5 py-1.5 text-xs text-muted-foreground">
                        <Loader2 className="size-3 animate-spin" aria-hidden />
                        Loading your categories…
                      </div>
                    ) : null}
                    <CommandEmpty className="py-4 text-muted-foreground">
                      Type a category to use it
                    </CommandEmpty>
                    <CommandGroup>
                      {typed && !exact ? (
                        <CommandItem
                          value={`use:${typed}`}
                          onSelect={() => choose(typed)}
                          className="[&>svg]:hidden"
                        >
                          Use “{typed}”
                        </CommandItem>
                      ) : null}
                      {matches.map((c) => (
                        <CommandItem
                          key={c.toLowerCase()}
                          value={c}
                          onSelect={() => choose(c)}
                          className="[&>svg]:hidden"
                        >
                          {c}
                        </CommandItem>
                      ))}
                    </CommandGroup>
                  </CommandList>
                </Command>
              </PopoverContent>
            </Popover>
            <FormError error={fieldState.error} />
          </Field>
        );
      }}
    />
  );
}

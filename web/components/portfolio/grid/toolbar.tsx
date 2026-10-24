"use client";

import { useEffect, useState } from "react";
import { Columns3, Search, X } from "lucide-react";
import type { ReactTable } from "@tanstack/react-table";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import type { FacetValue, HoldingRow } from "@/lib/types";
import { FacetedFilter, type FacetOption } from "./faceted-filter";
import type { gridFeatures } from "./features";
import { DateRangeFilter, PercentRangeFilter } from "./range-filters";
import type { FacetFilterDef, FilterDef, GridConfig } from "./types";
import type { FilterPatch, HoldingsFilters } from "./use-holdings-query";

/** Free-text facets get a search box beyond this many options. */
const SEARCHABLE_OVER = 6;

function facetOptions(
  def: FacetFilterDef,
  values: FacetValue[],
  selected: string[],
): FacetOption<string>[] {
  const counts = new Map(values.map((v) => [v.value, v.count]));
  const known = def.labels ? Object.keys(def.labels) : values.map((v) => v.value);
  const all = [...known, ...selected.filter((s) => !known.includes(s))];
  return all
    .filter((v) => counts.has(v) || selected.includes(v))
    .map((v) => ({
      value: v,
      label: def.labels?.[v] ?? v,
      count: counts.get(v) ?? 0,
    }));
}

const SEARCH_DEBOUNCE_MS = 300;

function SearchInput({
  value,
  placeholder,
  label,
  onSearch,
}: {
  value: string;
  placeholder: string;
  label: string;
  onSearch: (q: string) => void;
}) {
  const [text, setText] = useState(value);
  // Last value we pushed to the URL; used to tell our own echo from back/forward.
  const [sent, setSent] = useState(value);
  const [prevValue, setPrevValue] = useState(value);
  if (value !== prevValue) {
    setPrevValue(value);
    if (value !== sent) {
      setText(value);
      setSent(value);
    }
  }

  useEffect(() => {
    if (text.trim() === sent.trim()) return;
    const t = setTimeout(() => {
      setSent(text);
      onSearch(text);
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [text, sent, onSearch]);

  return (
    <div className="relative w-full sm:w-64">
      <Search
        aria-hidden
        className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground"
      />
      <Input
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={placeholder}
        aria-label={label}
        className="h-8 pl-8"
      />
    </div>
  );
}

export function Toolbar<TRow extends HoldingRow>({
  config,
  table,
  filters,
  facets,
  hasFilters,
  onFilters,
  onReset,
}: {
  config: GridConfig<TRow>;
  table: ReactTable<typeof gridFeatures, TRow>;
  filters: HoldingsFilters;
  facets: Record<string, FacetValue[]>;
  hasFilters: boolean;
  onFilters: (patch: FilterPatch) => void;
  onReset: () => void;
}) {
  function renderFilter(def: FilterDef) {
    if (def.kind === "facet") {
      const selected = filters.params[def.key] ?? [];
      const options = facetOptions(def, facets[def.key] ?? [], selected);
      return (
        <FacetedFilter
          key={def.key}
          title={def.title}
          options={options}
          selected={selected}
          searchable={!def.labels && options.length > SEARCHABLE_OVER}
          onChange={(next) => onFilters({ params: { [def.key]: next } })}
        />
      );
    }
    if (def.kind === "range") {
      return (
        <PercentRangeFilter
          key={def.minKey}
          title={def.title}
          min={filters.params[def.minKey]?.[0] ?? ""}
          max={filters.params[def.maxKey]?.[0] ?? ""}
          onChange={(min, max) =>
            onFilters({
              params: {
                [def.minKey]: min ? [min] : [],
                [def.maxKey]: max ? [max] : [],
              },
            })
          }
        />
      );
    }
    return (
      <DateRangeFilter
        key={def.fromKey}
        title={def.title}
        from={filters.params[def.fromKey]?.[0] ?? ""}
        to={filters.params[def.toKey]?.[0] ?? ""}
        onChange={(from, to) =>
          onFilters({
            params: {
              [def.fromKey]: from ? [from] : [],
              [def.toKey]: to ? [to] : [],
            },
          })
        }
      />
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <SearchInput
        value={filters.q}
        placeholder={config.searchPlaceholder}
        label={`Search ${config.noun}`}
        onSearch={(q) => onFilters({ q })}
      />
      {config.filters.map(renderFilter)}
      {hasFilters ? (
        <Button type="button" variant="ghost" size="sm" onClick={onReset}>
          <X aria-hidden />
          Reset
        </Button>
      ) : null}
      <div className="ml-auto">
        <DropdownMenu>
          <DropdownMenuTrigger
            render={<Button type="button" variant="outline" size="sm" />}
          >
            <Columns3 aria-hidden />
            Columns
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-44">
            {table
              .getAllLeafColumns()
              .filter((c) => c.getCanHide())
              .map((c) => (
                <DropdownMenuCheckboxItem
                  key={c.id}
                  checked={c.getIsVisible()}
                  onCheckedChange={(v) => c.toggleVisibility(v)}
                >
                  {config.columnLabels[c.id] ?? c.id}
                </DropdownMenuCheckboxItem>
              ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}

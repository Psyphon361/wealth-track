"use client";

import {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  useTransition,
  type RefObject,
} from "react";
import { usePathname, useRouter } from "next/navigation";
import { Command as CommandPrimitive } from "cmdk";
import { Loader2, Search, X } from "lucide-react";
import { Command, CommandGroup, CommandList } from "@/components/ui/command";
import {
  clearRecentQueries,
  EMPTY_RECENTS,
  getRecents,
  removeRecentOpened,
  removeRecentQuery,
  saveRecentOpened,
  saveRecentQuery,
  subscribeRecents,
} from "@/lib/search/recents";
import { cn } from "@/lib/utils";
import { buildModel, type Row } from "./search-model";
import { SearchRow, SkeletonRows, type RowContext, type Variant } from "./search-rows";
import {
  fetchSearchIndex,
  getSearchState,
  getServerSearchState,
  refreshSearchIndexIfNeeded,
  subscribeSearch,
} from "./search-store";

const NO_EXPANDED: ReadonlySet<string> = new Set();

export interface SearchPanelProps {
  variant: Variant;
  inputRef: RefObject<HTMLInputElement | null>;
  /** Apple platform (shortcut wording); null until known. */
  isMac: boolean | null;
  /** The on-screen keyboard is up (mobile): drops the bottom safe-area padding. */
  keyboardOpen: boolean;
  /** The user asked to close (Cancel, closing the current page). */
  onClose: () => void;
  /** A result was opened and the navigation finished: close without further history work. */
  onNavigated: () => void;
}

function Kbd({ children }: { children: string }) {
  return (
    <kbd className="rounded border border-border bg-muted/50 px-1 font-sans text-[11px] leading-4 text-muted-foreground">
      {children}
    </kbd>
  );
}

function Hint({ keys, label }: { keys: string[]; label: string }) {
  return (
    <span className="flex items-center gap-1">
      {keys.map((k) => (
        <Kbd key={k}>{k}</Kbd>
      ))}
      {label}
    </span>
  );
}

export function SearchPanel({ variant, inputRef, isMac, keyboardOpen, onClose, onNavigated }: SearchPanelProps) {
  const mobile = variant === "mobile";
  const router = useRouter();
  const pathname = usePathname();
  const search = useSyncExternalStore(subscribeSearch, getSearchState, getServerSearchState);
  const recents = useSyncExternalStore(subscribeRecents, getRecents, () => EMPTY_RECENTS);

  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(NO_EXPANDED);
  const [value, setValue] = useState("");
  const [seen, setSeen] = useState<{ q: string; sig: string } | null>(null);
  const [pendingValue, setPendingValue] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  /** Opened-holding order when the palette opened: keeps the ranking steady while it is open. */
  const [rankIds] = useState(() => getRecents().opened);

  const listRef = useRef<HTMLDivElement>(null);
  const modifierRef = useRef(false);
  const navigatingRef = useRef(false);
  const wasPendingRef = useRef(false);

  useEffect(() => {
    refreshSearchIndexIfNeeded();
    inputRef.current?.focus({ preventScroll: true });
  }, [inputRef]);

  const model = useMemo(
    () =>
      buildModel({
        query: deferredQuery,
        index: search.index,
        byKey: search.byKey,
        recents,
        rankIds,
        expanded,
        error: search.error,
      }),
    [deferredQuery, search.index, search.byKey, search.error, recents, rankIds, expanded],
  );

  // Selection follows the results: a new query selects the top row; other changes (index refresh,
  // expanding a group, removing a recent) keep the selected row while it is still listed.
  const sig = model.values.join("\n");
  if (seen === null || seen.q !== deferredQuery || seen.sig !== sig) {
    setSeen({ q: deferredQuery, sig });
    const sameQuery = seen !== null && seen.q === deferredQuery;
    if (!(sameQuery && model.values.includes(value))) setValue(model.values[0] ?? "");
  }

  useEffect(() => {
    listRef.current?.scrollTo({ top: 0 });
  }, [deferredQuery]);

  // Close once the navigation transition has finished.
  useEffect(() => {
    if (isPending) {
      wasPendingRef.current = true;
      return;
    }
    if (wasPendingRef.current) {
      wasPendingRef.current = false;
      onNavigated();
    }
  }, [isPending, onNavigated]);

  const scrollSelectedIntoView = useCallback(() => {
    requestAnimationFrame(() => {
      listRef.current
        ?.querySelector<HTMLElement>('[cmdk-item][aria-selected="true"]')
        ?.scrollIntoView({ block: "nearest" });
    });
  }, []);

  function open(row: Extract<Row, { href: string }>, newTab: boolean) {
    if (navigatingRef.current) return;
    if (row.kind === "holding") saveRecentOpened(`${row.match.item.type}:${row.match.item.id}`);
    else if (row.kind === "recent-holding") saveRecentOpened(row.recentKey);
    if (model.hasQuery && !model.noResults && row.kind !== "recent-holding") saveRecentQuery(query);
    if (newTab) {
      window.open(row.href, "_blank", "noopener");
      return;
    }
    if (row.href === pathname) {
      onClose();
      return;
    }
    navigatingRef.current = true;
    setPendingValue(row.value);
    startTransition(() => {
      // On mobile the palette pushed a history entry: replace it rather than stacking another.
      if (mobile) router.replace(row.href);
      else router.push(row.href);
    });
  }

  function onSelect(row: Row) {
    const newTab = modifierRef.current;
    modifierRef.current = false;
    switch (row.kind) {
      case "recent-query":
        setQuery(row.query);
        inputRef.current?.focus({ preventScroll: true });
        return;
      case "clear-queries":
        clearRecentQueries();
        return;
      case "more":
        if (row.expanded) {
          setExpanded((prev) => {
            const next = new Set(prev);
            next.delete(row.type);
            return next;
          });
        } else {
          setExpanded((prev) => new Set(prev).add(row.type));
          if (row.firstRevealed) {
            setValue(row.firstRevealed);
            scrollSelectedIntoView();
          }
        }
        return;
      case "retry":
        void fetchSearchIndex();
        return;
      default:
        open(row, newTab);
    }
  }

  function onRemove(row: Row) {
    if (row.kind === "recent-query") removeRecentQuery(row.query);
    else if (row.kind === "recent-holding") removeRecentOpened(row.recentKey);
  }

  const ctx: RowContext = {
    variant,
    pendingValue,
    loading: search.loading,
    onSelect,
    onRemove,
  };

  const refreshing = search.index !== null && search.loading;
  const liveText =
    model.hasQuery && !model.showSkeleton
      ? model.resultCount === 0
        ? "No results"
        : `${model.resultCount} ${model.resultCount === 1 ? "result" : "results"}`
      : "";

  return (
    <Command
      label="Search"
      shouldFilter={false}
      loop
      vimBindings={false}
      disablePointerSelection={mobile}
      value={value}
      onValueChange={setValue}
      onKeyDown={(e) => {
        // cmdk runs Enter without an event, so remember whether a modifier was held.
        if (e.key === "Enter") modifierRef.current = e.metaKey || e.ctrlKey;
      }}
      className={cn("p-0", mobile ? "h-full rounded-none!" : "rounded-xl!")}
    >
      <div
        className={cn(
          "flex shrink-0 items-center",
          mobile
            ? "gap-2 px-3 pt-[max(0.5rem,env(safe-area-inset-top))] pb-2"
            : "h-14 gap-3 border-b px-4",
        )}
      >
        <div
          className={cn(
            "flex min-w-0 flex-1 items-center gap-2",
            mobile && "h-11 rounded-xl border border-input bg-input/30 px-3",
          )}
        >
          <Search
            className={cn("shrink-0 text-muted-foreground", mobile ? "size-3.5" : "size-5")}
            aria-hidden
          />
          <CommandPrimitive.Input
            ref={inputRef}
            value={query}
            onValueChange={(v) => {
              setQuery(v);
              setExpanded((prev) => (prev.size ? NO_EXPANDED : prev));
            }}
            placeholder="Search holdings, pages, actions…"
            aria-label="Search"
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="off"
            spellCheck={false}
            enterKeyHint="search"
            className={cn(
              "min-w-0 flex-1 bg-transparent outline-hidden placeholder:text-muted-foreground",
              "h-full text-[16px]",
            )}
          />
          {refreshing ? (
            <Loader2 className="size-3.5 shrink-0 animate-spin text-muted-foreground" aria-hidden />
          ) : null}
          {mobile && query ? (
            <button
              type="button"
              aria-label="Clear search"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => {
                setQuery("");
                setExpanded(NO_EXPANDED);
                inputRef.current?.focus({ preventScroll: true });
              }}
              className="-mr-1.5 grid size-9 shrink-0 place-items-center rounded-md text-muted-foreground"
            >
              <X className="size-4" aria-hidden />
            </button>
          ) : null}
          {mobile ? null : <Kbd>esc</Kbd>}
        </div>
        {mobile ? (
          <button
            type="button"
            onClick={onClose}
            className="-mr-1 h-11 shrink-0 px-2 text-[16px] text-primary"
          >
            Cancel
          </button>
        ) : null}
      </div>

      <CommandList
        ref={listRef}
        // Keeps focus in the input when a row is clicked.
        onMouseDown={(e) => e.preventDefault()}
        onPointerDownCapture={(e) => {
          modifierRef.current = e.metaKey || e.ctrlKey;
        }}
        className={cn(
          mobile
            ? "max-h-none min-h-0 flex-1 overscroll-contain"
            : "max-h-[70vh] overscroll-contain",
        )}
        style={
          mobile && !keyboardOpen
            ? { paddingBottom: "env(safe-area-inset-bottom)" }
            : undefined
        }
      >
        {model.noResults ? (
          <div className="px-4 pt-6 pb-2 text-center text-[13.5px] break-words text-muted-foreground">
            No results for “{deferredQuery.trim()}”
          </div>
        ) : null}
        {model.sections.map((section) => (
          <CommandGroup key={section.id} heading={section.heading}>
            {section.id === "retry" && search.error ? (
              <div role="alert" className="px-1.5 pt-1 pb-1.5 text-[13.5px]">
                <p className="font-medium text-foreground">{search.error.message}</p>
                {search.error.description ? (
                  <p className="text-xs text-muted-foreground">{search.error.description}</p>
                ) : null}
              </div>
            ) : null}
            {section.rows.map((row) => (
              <SearchRow key={row.value} row={row} ctx={ctx} />
            ))}
          </CommandGroup>
        ))}
        {model.showSkeleton ? <SkeletonRows mobile={mobile} /> : null}
      </CommandList>

      {mobile ? null : (
        <div className="flex shrink-0 items-center gap-4 border-t px-4 py-2.5 text-[12.5px] text-muted-foreground">
          <Hint keys={["↑", "↓"]} label="navigate" />
          <Hint keys={["↵"]} label="open" />
          <Hint keys={[isMac ? "⌘↵" : "Ctrl ↵"]} label="new tab" />
          <Hint keys={["esc"]} label="close" />
        </div>
      )}

      <div className="sr-only" role="status" aria-live="polite">
        {liveText}
      </div>
    </Command>
  );
}

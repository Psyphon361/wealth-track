"use client";

import type { ReactNode } from "react";
import {
  ChevronDown,
  ChevronUp,
  FileUp,
  History,
  LayoutDashboard,
  Loader2,
  Plus,
  RotateCw,
  Shapes,
  Trash2,
  X,
  type LucideIcon,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { CommandItem } from "@/components/ui/command";
import { Skeleton } from "@/components/ui/skeleton";
import { getAssetEntry } from "@/lib/asset-catalog";
import { formatINR, formatPct } from "@/lib/format";
import type { NotesSnippet, SearchIndexItem, StaticEntry, TextRange } from "@/lib/search/types";
import { cn } from "@/lib/utils";
import type { Row } from "./search-model";

export type Variant = "desktop" | "mobile";

export interface RowContext {
  variant: Variant;
  /** Value of the row being opened (spinner, dimmed). */
  pendingValue: string | null;
  /** The index request is running (Retry spinner). */
  loading: boolean;
  onSelect: (row: Row) => void;
  onRemove: (row: Row) => void;
}

function Highlight({ text, ranges }: { text: string; ranges: TextRange[] }) {
  if (ranges.length === 0) return <>{text}</>;
  const parts: ReactNode[] = [];
  let pos = 0;
  ranges.forEach(([start, end], i) => {
    const s = Math.max(start, pos);
    const e = Math.min(end, text.length);
    if (e <= s) return;
    if (s > pos) parts.push(text.slice(pos, s));
    parts.push(
      <span key={i} className="font-semibold text-foreground">
        {text.slice(s, e)}
      </span>,
    );
    pos = e;
  });
  if (pos < text.length) parts.push(text.slice(pos));
  return <>{parts}</>;
}

function iconFor(type: string): LucideIcon {
  return getAssetEntry(type)?.icon ?? Shapes;
}

function staticIcon(entry: StaticEntry): LucideIcon {
  if (entry.id === "action-import-cas") return FileUp;
  if (entry.iconType) return iconFor(entry.iconType);
  if (entry.id === "goto-dashboard") return LayoutDashboard;
  if (entry.id === "goto-deleted") return Trash2;
  return Plus;
}

function Tile({ icon: Icon, tinted, mobile }: { icon: LucideIcon; tinted: boolean; mobile: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(
        "flex shrink-0 items-center justify-center rounded-md",
        mobile ? "size-8" : "size-9",
        tinted ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground",
      )}
    >
      <Icon className={mobile ? "size-3.5" : "size-4"} />
    </span>
  );
}

/** Empty marker: its presence hides CommandItem's built-in (invisible) check icon. */
function NoCheck() {
  return <span data-slot="command-shortcut" className="hidden" />;
}

function RemoveButton({ label, onRemove, mobile }: { label: string; onRemove: () => void; mobile: boolean }) {
  return (
    <button
      type="button"
      tabIndex={-1}
      aria-label={label}
      data-slot="command-shortcut"
      // Keeps focus in the search input.
      onMouseDown={(e) => e.preventDefault()}
      onClick={(e) => {
        // Must not also select (open) the row.
        e.stopPropagation();
        onRemove();
      }}
      className={cn(
        "ml-1 grid shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-background hover:text-foreground",
        mobile
          ? "size-9"
          : "size-7 opacity-0 group-hover/command-item:opacity-100 group-data-selected/command-item:opacity-100",
      )}
    >
      <X className="size-3.5" aria-hidden />
    </button>
  );
}

function gainTone(pct: number): string {
  return pct > 0 ? "text-gain" : pct < 0 ? "text-loss" : "text-muted-foreground";
}

function HoldingBody({
  item,
  titleRanges,
  notes,
  mobile,
  pending,
}: {
  item: SearchIndexItem;
  titleRanges: TextRange[];
  notes: NotesSnippet | null;
  mobile: boolean;
  pending: boolean;
}) {
  return (
    <>
      <Tile icon={iconFor(item.type)} tinted mobile={mobile} />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="flex min-w-0 items-center gap-1.5">
          <span className={cn("truncate text-foreground/80", !mobile && "text-[14.5px]")}>
            <Highlight text={item.title} ranges={titleRanges} />
          </span>
          {item.status === "matured" ? (
            <Badge variant="secondary" className="h-4 px-1.5 text-[10.5px] text-muted-foreground">
              Matured
            </Badge>
          ) : null}
        </span>
        {item.subtitle ? (
          <span className={cn("truncate text-muted-foreground", mobile ? "text-xs" : "text-[13px]")}>
            {item.subtitle}
          </span>
        ) : null}
        {notes ? (
          <span className={cn("truncate text-muted-foreground/80", mobile ? "text-xs" : "text-[13px]")}>
            <Highlight text={notes.text} ranges={notes.ranges} />
          </span>
        ) : null}
      </span>
      {pending ? (
        <Loader2 data-slot="command-shortcut" className="ml-auto size-3.5 animate-spin" aria-hidden />
      ) : (
        <span
          data-slot="command-shortcut"
          className="ml-auto flex shrink-0 flex-col items-end pl-2 leading-tight"
        >
          <span className={cn("num whitespace-nowrap text-foreground", mobile ? "text-[13px]" : "text-[14px]")}>
            {formatINR(item.current_value)}
          </span>
          {item.gain_pct !== null ? (
            <span
              className={cn(
                "num whitespace-nowrap",
                mobile ? "text-[11.5px]" : "text-[12px]",
                gainTone(item.gain_pct),
              )}
            >
              {item.gain_pct > 0 ? "+" : ""}
              {formatPct(item.gain_pct)}
            </span>
          ) : null}
        </span>
      )}
    </>
  );
}

export function SearchRow({ row, ctx }: { row: Row; ctx: RowContext }) {
  const mobile = ctx.variant === "mobile";
  const itemClass = cn("gap-2.5", mobile ? "min-h-11 px-2 py-1.5" : "px-2.5 py-2");
  const select = () => ctx.onSelect(row);

  switch (row.kind) {
    case "holding": {
      const pending = ctx.pendingValue === row.value;
      return (
        <CommandItem
          value={row.value}
          onSelect={select}
          className={cn(itemClass, pending && "opacity-60")}
          aria-busy={pending || undefined}
        >
          <HoldingBody
            item={row.match.item}
            titleRanges={row.match.titleRanges}
            notes={row.match.notesSnippet}
            mobile={mobile}
            pending={pending}
          />
        </CommandItem>
      );
    }
    case "recent-holding": {
      const pending = ctx.pendingValue === row.value;
      return (
        <CommandItem
          value={row.value}
          onSelect={select}
          className={cn(itemClass, pending && "opacity-60")}
          aria-busy={pending || undefined}
        >
          <HoldingBody item={row.item} titleRanges={[]} notes={null} mobile={mobile} pending={pending} />
          {pending ? null : (
            <RemoveButton
              label={`Remove ${row.item.title} from recently opened`}
              onRemove={() => ctx.onRemove(row)}
              mobile={mobile}
            />
          )}
        </CommandItem>
      );
    }
    case "static": {
      const pending = ctx.pendingValue === row.value;
      const isAsset = Boolean(row.entry.iconType) && row.entry.id !== "action-import-cas";
      return (
        <CommandItem
          value={row.value}
          onSelect={select}
          className={cn(itemClass, pending && "opacity-60")}
          aria-busy={pending || undefined}
        >
          <Tile icon={staticIcon(row.entry)} tinted={isAsset} mobile={mobile} />
          <span className="min-w-0 flex-1 truncate text-foreground/80">
            <Highlight text={row.entry.title} ranges={row.ranges} />
          </span>
          {pending ? (
            <Loader2 data-slot="command-shortcut" className="ml-auto size-3.5 animate-spin" aria-hidden />
          ) : mobile ? (
            <NoCheck />
          ) : (
            <span
              data-slot="command-shortcut"
              aria-hidden
              className="ml-auto hidden text-xs text-muted-foreground group-data-selected/command-item:inline"
            >
              ↵
            </span>
          )}
        </CommandItem>
      );
    }
    case "recent-query":
      return (
        <CommandItem value={row.value} onSelect={select} className={itemClass}>
          <Tile icon={History} tinted={false} mobile={mobile} />
          <span className="min-w-0 flex-1 truncate text-foreground/80">{row.query}</span>
          <RemoveButton
            label={`Remove ${row.query} from recent searches`}
            onRemove={() => ctx.onRemove(row)}
            mobile={mobile}
          />
        </CommandItem>
      );
    case "clear-queries":
      return (
        <CommandItem value={row.value} onSelect={select} className={cn(itemClass, "text-muted-foreground")}>
          <Tile icon={Trash2} tinted={false} mobile={mobile} />
          <span className="min-w-0 flex-1 truncate">Clear recent searches</span>
          <NoCheck />
        </CommandItem>
      );
    case "more":
      return (
        <CommandItem value={row.value} onSelect={select} className={cn(itemClass, "text-muted-foreground")}>
          <span aria-hidden className={cn("flex shrink-0 items-center justify-center", mobile ? "size-8" : "size-9")}>
            {row.expanded ? (
              <ChevronUp className={mobile ? "size-3.5" : "size-4"} />
            ) : (
              <ChevronDown className={mobile ? "size-3.5" : "size-4"} />
            )}
          </span>
          <span className="num min-w-0 flex-1 truncate">
            {row.expanded ? `Show fewer ${row.typeLabel}` : `+${row.hidden} more`}
          </span>
          <NoCheck />
        </CommandItem>
      );
    case "retry":
      return (
        <CommandItem value={row.value} onSelect={select} className={itemClass} aria-busy={ctx.loading || undefined}>
          <span aria-hidden className={cn("flex shrink-0 items-center justify-center", mobile ? "size-8" : "size-9")}>
            {ctx.loading ? (
              <Loader2 className={cn("animate-spin", mobile ? "size-3.5" : "size-4")} />
            ) : (
              <RotateCw className={mobile ? "size-3.5" : "size-4"} />
            )}
          </span>
          <span className="min-w-0 flex-1 truncate">Retry</span>
          <NoCheck />
        </CommandItem>
      );
  }
}

export function SkeletonRows({ count = 3, mobile }: { count?: number; mobile: boolean }) {
  return (
    <div aria-busy="true" className="px-1 pb-1">
      {Array.from({ length: count }, (_, i) => (
        <div
          key={i}
          className={cn("flex items-center gap-2.5", mobile ? "min-h-11 px-2 py-1.5" : "min-h-14 px-2.5 py-2")}
        >
          <Skeleton className={cn("shrink-0", mobile ? "size-8" : "size-9")} />
          <div className="flex min-w-0 flex-1 flex-col gap-1.5">
            <Skeleton className={cn("w-2/5", mobile ? "h-3" : "h-3.5")} />
            <Skeleton className={cn("w-1/4", mobile ? "h-2.5" : "h-3")} />
          </div>
          <Skeleton className={cn("shrink-0", mobile ? "h-3 w-16" : "h-3.5 w-20")} />
        </div>
      ))}
    </div>
  );
}

import type { ApiMessage } from "@/lib/api";
import { groupMatches, parseQuery, rankHoldings, type PreparedItem } from "@/lib/search/rank";
import type { Recents } from "@/lib/search/recents";
import { rankStatic, STATIC_ENTRIES } from "@/lib/search/static-entries";
import type {
  HoldingMatch,
  SearchIndexItem,
  StaticEntry,
  TextRange,
} from "@/lib/search/types";

export const PER_GROUP = 5;
const STATIC_LIMIT = 5;
const QUICK_LINK_IDS = ["goto-dashboard", "action-add", "goto-deleted"];
const NO_RESULT_LINK_IDS = ["goto-deleted", "action-add"];

/** One selectable row. `value` is the unique cmdk value. */
export type Row =
  | { kind: "holding"; value: string; match: HoldingMatch; href: string }
  | { kind: "recent-holding"; value: string; item: SearchIndexItem; href: string; recentKey: string }
  | { kind: "static"; value: string; entry: StaticEntry; ranges: TextRange[]; href: string }
  | { kind: "recent-query"; value: string; query: string }
  | { kind: "clear-queries"; value: string }
  | {
      kind: "more";
      value: string;
      type: string;
      typeLabel: string;
      hidden: number;
      expanded: boolean;
      firstRevealed: string | null;
    }
  | { kind: "retry"; value: string };

export interface Section {
  id: string;
  heading?: string;
  rows: Row[];
}

export interface SearchModel {
  hasQuery: boolean;
  sections: Section[];
  /** Selectable row values in display order. */
  values: string[];
  /** Holdings and pages matching the query (for the screen reader count). */
  resultCount: number;
  /** The index is ready and nothing matched. */
  noResults: boolean;
  /** First load in progress: the holdings area shows placeholders. */
  showSkeleton: boolean;
  /** First load failed and there is no data to fall back on. */
  showError: boolean;
}

export interface ModelInput {
  query: string;
  index: PreparedItem[] | null;
  byKey: Map<string, SearchIndexItem> | null;
  recents: Recents;
  /** Opened holdings used as a ranking tie-break (fixed for one palette session). */
  rankIds: readonly string[];
  expanded: ReadonlySet<string>;
  error: ApiMessage | null;
}

export function holdingHref(type: string, id: number): string {
  return `/portfolio/${type}/${id}`;
}

const STATIC_BY_ID = new Map(STATIC_ENTRIES.map((e) => [e.id, e]));

function staticRow(entry: StaticEntry, ranges: TextRange[] = []): Row {
  return { kind: "static", value: `s:${entry.id}`, entry, ranges, href: entry.href };
}

function staticRowsById(ids: string[]): Row[] {
  const rows: Row[] = [];
  for (const id of ids) {
    const entry = STATIC_BY_ID.get(id);
    if (entry) rows.push(staticRow(entry));
  }
  return rows;
}

function finish(
  base: Omit<SearchModel, "values">,
): SearchModel {
  const values = base.sections.flatMap((s) => s.rows.map((r) => r.value));
  return { ...base, values };
}

export function buildModel({
  query,
  index,
  byKey,
  recents,
  rankIds,
  expanded,
  error,
}: ModelInput): SearchModel {
  const hasQuery = parseQuery(query).tokens.length > 0;
  const waiting = index === null && error === null;
  const showError = index === null && error !== null;

  if (!hasQuery) {
    const sections: Section[] = [];
    const openedRows: Row[] = [];
    if (byKey) {
      for (const key of recents.opened) {
        const item = byKey.get(key);
        if (item) {
          openedRows.push({
            kind: "recent-holding",
            value: `ro:${key}`,
            item,
            href: holdingHref(item.type, item.id),
            recentKey: key,
          });
        }
      }
    }
    if (openedRows.length) sections.push({ id: "recent-opened", heading: "Recently opened", rows: openedRows });
    if (recents.queries.length) {
      const rows: Row[] = recents.queries.map((q, i) => ({ kind: "recent-query", value: `rq:${i}`, query: q }));
      rows.push({ kind: "clear-queries", value: "clear-queries" });
      sections.push({ id: "recent-queries", heading: "Recent searches", rows });
    }
    sections.push({ id: "quick", heading: "Quick links", rows: staticRowsById(QUICK_LINK_IDS) });
    if (showError) sections.push({ id: "retry", rows: [{ kind: "retry", value: "retry" }] });
    return finish({
      hasQuery,
      sections,
      resultCount: 0,
      noResults: false,
      showSkeleton: waiting && recents.opened.length > 0,
      showError,
    });
  }

  const matches = index ? rankHoldings(index, query, { recentIds: rankIds }) : [];
  const groups = groupMatches(matches, { perGroup: PER_GROUP, expanded });
  const statics = rankStatic(query);
  const goto = statics.filter((s) => s.entry.kind === "goto").slice(0, STATIC_LIMIT);
  const actions = statics.filter((s) => s.entry.kind === "action").slice(0, STATIC_LIMIT);

  const holdingSections: Section[] = groups.map((g) => {
    const rows: Row[] = g.matches.map((match) => ({
      kind: "holding",
      value: `h:${match.item.type}:${match.item.id}`,
      match,
      href: holdingHref(match.item.type, match.item.id),
    }));
    if (g.hiddenCount > 0 || (expanded.has(g.type) && g.matches.length > PER_GROUP)) {
      const first = g.hiddenCount > 0 ? matches.filter((m) => m.item.type === g.type)[PER_GROUP] : undefined;
      rows.push({
        kind: "more",
        value: `m:${g.type}`,
        type: g.type,
        typeLabel: g.type_label,
        hidden: g.hiddenCount,
        expanded: g.hiddenCount === 0,
        firstRevealed: first ? `h:${first.item.type}:${first.item.id}` : null,
      });
    }
    return { id: `type-${g.type}`, heading: g.type_label, rows };
  });

  const staticSections: Section[] = [];
  if (goto.length) {
    staticSections.push({ id: "goto", heading: "Go to", rows: goto.map((s) => staticRow(s.entry, s.titleRanges)) });
  }
  if (actions.length) {
    staticSections.push({
      id: "actions",
      heading: "Actions",
      rows: actions.map((s) => staticRow(s.entry, s.titleRanges)),
    });
  }

  const bestStatic = Math.min(...[...goto, ...actions].map((s) => s.tier));
  const staticFirst = matches.length > 0 && staticSections.length > 0 && bestStatic < matches[0].tier;
  const sections = staticFirst ? [...staticSections, ...holdingSections] : [...holdingSections, ...staticSections];

  const noResults = index !== null && matches.length === 0 && staticSections.length === 0;
  if (noResults) {
    sections.push({ id: "no-results-links", rows: staticRowsById(NO_RESULT_LINK_IDS) });
  }
  if (showError) sections.push({ id: "retry", rows: [{ kind: "retry", value: "retry" }] });

  return finish({
    hasQuery,
    sections,
    resultCount: matches.length + goto.length + actions.length,
    noResults,
    showSkeleton: waiting,
    showError,
  });
}

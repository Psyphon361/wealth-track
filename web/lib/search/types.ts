import type { AssetType } from "../types";

/** One row of the search index API: everything the palette needs to rank and show a holding. */
export interface SearchIndexItem {
  type: string;
  type_label: string;
  id: number;
  title: string;
  subtitle: string | null;
  terms: { ids: string[]; strong: string[]; weak: string[] };
  notes: string | null;
  current_value: number;
  gain_pct: number | null;
  status: string;
  updated_at: string;
}

/** [start, end) indexes into the ORIGINAL string. */
export type TextRange = [number, number];

export interface NotesSnippet {
  text: string;
  ranges: TextRange[];
}

export interface HoldingMatch {
  item: SearchIndexItem;
  /** Best match tier, 1 (exact id) to 9 (notes). Lower is better. */
  tier: number;
  titleRanges: TextRange[];
  /** Set when a token is found only in the notes. */
  notesSnippet: NotesSnippet | null;
}

export interface MatchGroup {
  type: string;
  type_label: string;
  /** Visible rows. */
  matches: HoldingMatch[];
  hiddenCount: number;
}

export interface StaticEntry {
  id: string;
  kind: "goto" | "action";
  title: string;
  href: string;
  aliases: string[];
  iconType?: AssetType;
}

export interface StaticMatch {
  entry: StaticEntry;
  tier: number;
  titleRanges: TextRange[];
}

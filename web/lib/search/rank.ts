import { compact, normalize, normalizeMapped, type Normalized } from "./normalize";
import type {
  HoldingMatch,
  MatchGroup,
  NotesSnippet,
  SearchIndexItem,
  TextRange,
} from "./types";

const WEAK_RANK = 7.5;
const NOTES_RANK = 9;
const SNIPPET_LEN = 80;

/** Normalised text an item can be matched on. Shared by holdings and static entries. */
export interface Fields {
  title: string;
  words: string[];
  /** Compact (no spaces) ids. */
  ids: string[];
  strong: string[];
  weak: string[];
  notes: string | null;
  /** Strings that rank like a title prefix when the whole query is their prefix (aliases). */
  lead: string[];
}

export interface ParsedQuery {
  text: string;
  compact: string;
  tokens: string[];
}

export interface Score {
  /** Integer tier, 1 to 9. */
  tier: number;
  /** Best rank; like tier, but weak terms (7.5) sort after strong ones (7). */
  rank: number;
  /** Sum of each token's own best rank. */
  sum: number;
  /** First token whose best match is in the notes. */
  notesToken: string | null;
}

export interface PreparedItem extends Fields {
  item: SearchIndexItem;
  titleN: Normalized;
  notesN: Normalized | null;
}

export function parseQuery(query: string): ParsedQuery {
  const text = normalize(query);
  return { text, compact: text.replace(/ /g, ""), tokens: text === "" ? [] : text.split(" ") };
}

/** Damerau-Levenshtein (adjacent transposition counts as one edit). Returns max + 1 when over max. */
export function editDistance(a: string, b: string, max: number): number {
  if (Math.abs(a.length - b.length) > max) return max + 1;
  let older: number[] = [];
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const row = [i];
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      let v = Math.min(prev[j] + 1, row[j - 1] + 1, prev[j - 1] + cost);
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
        v = Math.min(v, older[j - 2] + 1);
      }
      row.push(v);
    }
    older = prev;
    prev = row;
  }
  return prev[b.length];
}

function typoLimit(token: string): number {
  if (token.length < 4) return 0;
  return token.length >= 8 ? 2 : 1;
}

/** Best rank of one token in the fields, or null. */
function tokenRank(f: Fields, tok: string): number | null {
  if (f.words.some((w) => w.startsWith(tok))) return 4;
  if (f.ids.some((id) => id.startsWith(tok))) return 5;
  if (tok.length < 2) return null;
  if (f.title.includes(tok)) return 6;
  if (f.strong.some((s) => s.includes(tok))) return 7;
  if (f.weak.some((s) => s.includes(tok))) return WEAK_RANK;
  const max = typoLimit(tok);
  if (max && f.words.some((w) => editDistance(w, tok, max) <= max)) return 8;
  if (f.notes?.includes(tok)) return NOTES_RANK;
  return null;
}

/** Scores fields against a query (every token must match), or null when they do not match. */
export function scoreFields(f: Fields, q: ParsedQuery): Score | null {
  if (f.ids.includes(q.compact)) return { tier: 1, rank: 1, sum: 0, notesToken: null };
  let rank = Infinity;
  let lenient = false;
  if (f.title === q.text) rank = 2;
  else if (f.title.startsWith(q.text)) rank = 3;
  else if (f.lead.some((a) => a.startsWith(q.text))) {
    rank = 3;
    lenient = true;
  }
  let sum = 0;
  let notesToken: string | null = null;
  for (const tok of q.tokens) {
    let r = tokenRank(f, tok);
    if (r === null) {
      if (!lenient) return null;
      r = 4;
    }
    if (r === NOTES_RANK && notesToken === null) notesToken = tok;
    rank = Math.min(rank, r);
    sum += r;
  }
  return { tier: Math.floor(rank), rank, sum, notesToken };
}

/** Highlight spans in the normalised text, translated back to the original string. */
export function rangesFor(n: Normalized, tokens: string[]): TextRange[] {
  const words = [...n.text.matchAll(/\S+/g)].map((m) => ({ w: m[0], at: m.index ?? 0 }));
  const spans: TextRange[] = [];
  for (const tok of tokens) {
    if (tok.length === 1) {
      for (const { w, at } of words) if (w.startsWith(tok)) spans.push([at, at + 1]);
      continue;
    }
    let found = false;
    for (let at = n.text.indexOf(tok); at >= 0; at = n.text.indexOf(tok, at + tok.length)) {
      spans.push([at, at + tok.length]);
      found = true;
    }
    const max = typoLimit(tok);
    if (!found && max) {
      for (const { w, at } of words) {
        if (editDistance(w, tok, max) <= max) spans.push([at, at + w.length]);
      }
    }
  }
  const mapped = spans
    .map(([s, e]): TextRange => [n.starts[s], n.ends[e - 1]])
    .sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const merged: TextRange[] = [];
  for (const r of mapped) {
    const last = merged[merged.length - 1];
    if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1]);
    else merged.push([r[0], r[1]]);
  }
  return merged;
}

/** About 80 characters of the notes around the first hit of `tok`, cut on word boundaries. */
function notesSnippet(raw: string, n: Normalized, tok: string, tokens: string[]): NotesSnippet {
  const at = n.text.indexOf(tok);
  const start = n.starts[at];
  const end = n.ends[at + tok.length - 1];
  const room = Math.max(0, SNIPPET_LEN - (end - start));
  let lo = Math.max(0, start - Math.floor(room / 2));
  let hi = Math.min(raw.length, end + Math.ceil(room / 2));
  const space = (k: number) => /\s/.test(raw[k]);
  while (lo > 0 && lo < start && !space(lo - 1)) lo++;
  while (lo > 0 && !space(lo - 1)) lo--;
  while (hi < raw.length && hi > end && !space(hi)) hi--;
  while (hi < raw.length && !space(hi)) hi++;
  while (lo < start && space(lo)) lo++;
  while (hi > end && space(hi - 1)) hi--;
  const body = raw.slice(lo, hi);
  const prefix = lo > 0 ? "…" : "";
  const suffix = hi < raw.length ? "…" : "";
  const ranges = rangesFor(normalizeMapped(body), tokens).map(
    ([s, e]): TextRange => [s + prefix.length, e + prefix.length],
  );
  return { text: prefix + body + suffix, ranges };
}

/** Normalises every searchable field once, so each keystroke only compares strings. */
export function prepareIndex(items: SearchIndexItem[]): PreparedItem[] {
  return items.map((item) => {
    const titleN = normalizeMapped(item.title);
    const notesN = item.notes ? normalizeMapped(item.notes) : null;
    return {
      item,
      titleN,
      notesN,
      title: titleN.text,
      words: titleN.text.split(" "),
      ids: item.terms.ids.map(compact).filter(Boolean),
      strong: item.terms.strong.map(normalize).filter(Boolean),
      weak: [...item.terms.weak, item.subtitle ?? "", item.type_label]
        .map(normalize)
        .filter(Boolean),
      notes: notesN?.text || null,
      lead: [],
    };
  });
}

function compareNumbers(a: number, b: number): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/**
 * Matches for the query, best first: tier, then token sum, then active status, recently opened
 * (`recentIds` are "type:id", most recent first), value (descending) and title.
 */
export function rankHoldings(
  index: PreparedItem[],
  query: string,
  opts: { recentIds?: readonly string[] } = {},
): HoldingMatch[] {
  const q = parseQuery(query);
  if (q.tokens.length === 0) return [];
  const recent = new Map<string, number>();
  (opts.recentIds ?? []).forEach((key, i) => {
    if (!recent.has(key)) recent.set(key, i);
  });
  const recency = (p: PreparedItem) => recent.get(`${p.item.type}:${p.item.id}`) ?? Infinity;

  const scored: { p: PreparedItem; s: Score }[] = [];
  for (const p of index) {
    const s = scoreFields(p, q);
    if (s) scored.push({ p, s });
  }
  scored.sort(
    (a, b) =>
      a.s.rank - b.s.rank ||
      a.s.sum - b.s.sum ||
      compareNumbers(a.p.item.status === "active" ? 0 : 1, b.p.item.status === "active" ? 0 : 1) ||
      compareNumbers(recency(a.p), recency(b.p)) ||
      b.p.item.current_value - a.p.item.current_value ||
      a.p.item.title.localeCompare(b.p.item.title),
  );
  return scored.map(({ p, s }) => ({
    item: p.item,
    tier: s.tier,
    titleRanges: rangesFor(p.titleN, q.tokens),
    notesSnippet:
      s.notesToken && p.notesN && p.item.notes
        ? notesSnippet(p.item.notes, p.notesN, s.notesToken, q.tokens)
        : null,
  }));
}

/**
 * Groups matches by asset type, groups ordered by their best match. Each shows `perGroup` rows
 * (default 5) unless its type is in `expanded`.
 */
export function groupMatches(
  matches: HoldingMatch[],
  opts: { perGroup?: number; expanded?: ReadonlySet<string> } = {},
): MatchGroup[] {
  const perGroup = opts.perGroup ?? 5;
  const byType = new Map<string, HoldingMatch[]>();
  for (const m of matches) {
    const list = byType.get(m.item.type);
    if (list) list.push(m);
    else byType.set(m.item.type, [m]);
  }
  return [...byType.entries()].map(([type, all]) => {
    const visible = opts.expanded?.has(type) ? all : all.slice(0, perGroup);
    return {
      type,
      type_label: all[0].item.type_label,
      matches: visible,
      hiddenCount: all.length - visible.length,
    };
  });
}

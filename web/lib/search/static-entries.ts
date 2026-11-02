import { ASSET_CATALOG } from "../asset-catalog";
import { normalize, normalizeMapped, type Normalized } from "./normalize";
import { parseQuery, rangesFor, scoreFields, type Fields } from "./rank";
import type { StaticEntry, StaticMatch } from "./types";

/** Shorthand people type for each asset type. Types missing here still get their title. */
const TYPE_ALIASES: Record<string, string[]> = {
  fd: ["fd", "fixed deposit", "term deposit"],
  rd: ["rd", "recurring deposit"],
  cash: ["savings", "current account", "cash", "bank account"],
  pf: ["pf", "epf", "ppf", "vpf", "provident fund"],
  stock: ["stocks", "shares", "equity"],
  mf: ["mf", "mutual fund", "mutual funds"],
  nps: ["nps", "pension"],
  bond: ["bonds", "sgb", "sovereign gold bond", "debenture"],
  gold: ["gold", "silver", "metal"],
  other: ["crypto", "bitcoin", "property"],
};

export const STATIC_ENTRIES: StaticEntry[] = [
  {
    id: "goto-dashboard",
    kind: "goto",
    title: "Dashboard",
    href: "/dashboard",
    aliases: ["home", "net worth", "overview"],
  },
  ...ASSET_CATALOG.map(
    (a): StaticEntry => ({
      id: `goto-${a.type}`,
      kind: "goto",
      title: a.title,
      href: `/portfolio/${a.type}`,
      aliases: TYPE_ALIASES[a.type] ?? [],
      iconType: a.type,
    }),
  ),
  {
    id: "goto-deleted",
    kind: "goto",
    title: "Recently deleted",
    href: "/deleted",
    aliases: ["deleted", "trash", "bin", "restore"],
  },
  {
    id: "action-add",
    kind: "action",
    title: "Add asset",
    href: "/add",
    aliases: ["new asset", "create", "gallery"],
  },
  ...ASSET_CATALOG.map(
    (a): StaticEntry => ({
      id: `action-add-${a.type}`,
      kind: "action",
      title: `Add ${a.title}`,
      href: `/add/${a.type}`,
      aliases: TYPE_ALIASES[a.type] ?? [],
      iconType: a.type,
    }),
  ),
  {
    id: "action-import-cas",
    kind: "action",
    title: "Import CAS",
    href: "/add/mf",
    aliases: ["cas", "mutual fund import", "statement", "cams", "kfintech"],
    iconType: "mf",
  },
];

interface PreparedEntry {
  entry: StaticEntry;
  titleN: Normalized;
  fields: Fields;
}

const PREPARED: PreparedEntry[] = STATIC_ENTRIES.map((entry) => {
  const titleN = normalizeMapped(entry.title);
  const aliases = entry.aliases.map(normalize);
  return {
    entry,
    titleN,
    fields: {
      title: titleN.text,
      words: titleN.text.split(" "),
      ids: [],
      strong: aliases,
      weak: [],
      notes: null,
      lead: aliases,
    },
  };
});

/** Go-to and action entries matching the query, best first (ties keep list order). Empty query: none. */
export function rankStatic(query: string): StaticMatch[] {
  const q = parseQuery(query);
  if (q.tokens.length === 0) return [];
  const scored: { p: PreparedEntry; rank: number; exact: number; sum: number; tier: number; at: number }[] = [];
  PREPARED.forEach((p, at) => {
    const s = scoreFields(p.fields, q);
    // An alias typed in full ("cas") beats entries that only start with it.
    if (s) scored.push({ p, rank: s.rank, exact: p.fields.lead.includes(q.text) ? 0 : 1, sum: s.sum, tier: s.tier, at });
  });
  scored.sort((a, b) => a.rank - b.rank || a.exact - b.exact || a.sum - b.sum || a.at - b.at);
  return scored.map(({ p, tier }) => ({
    entry: p.entry,
    tier,
    titleRanges: rangesFor(p.titleN, q.tokens),
  }));
}

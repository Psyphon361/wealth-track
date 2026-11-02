import { describe, expect, it } from "vitest";
import {
  editDistance,
  groupMatches,
  highlightRanges,
  prepareIndex,
  rankHoldings,
} from "./rank";
import type { SearchIndexItem } from "./types";

let nextId = 1;

type Extra = Partial<Omit<SearchIndexItem, "terms">> & { terms?: Partial<SearchIndexItem["terms"]> };

function make(title: string, extra: Extra = {}): SearchIndexItem {
  const { terms, ...rest } = extra;
  return {
    type: "stock",
    type_label: "Stocks",
    id: nextId++,
    title,
    subtitle: null,
    terms: { ids: [], strong: [], weak: [], ...terms },
    notes: null,
    current_value: 1000,
    gain_pct: null,
    status: "active",
    updated_at: "2026-11-01",
    ...rest,
  };
}

function titles(items: SearchIndexItem[], query: string, recentIds: string[] = []): string[] {
  return rankHoldings(prepareIndex(items), query, { recentIds }).map((m) => m.item.title);
}

function tierOf(items: SearchIndexItem[], query: string, title: string): number | undefined {
  return rankHoldings(prepareIndex(items), query).find((m) => m.item.title === title)?.tier;
}

describe("tiers", () => {
  const items = [
    make("Zeta", { terms: { ids: ["GOLD"] }, current_value: 1 }),
    make("Gold", { current_value: 10 }),
    make("Gold Fund", { current_value: 100 }),
    make("Sovereign Gold Bond", { current_value: 1000 }),
    make("Nothing", { terms: { ids: ["GOLD123"] }, current_value: 10_000 }),
    make("Bangold", { current_value: 100_000 }),
    make("Strong hit", { terms: { strong: ["gold rated"] }, current_value: 1_000_000 }),
    make("Weak hit", { terms: { weak: ["gold link"] }, current_value: 10_000_000 }),
    make("Notes hit", { notes: "bought some gold last year", current_value: 1e12 }),
  ];

  it("orders tiers 1 to 9 even though value rises the other way", () => {
    const out = rankHoldings(prepareIndex(items), "gold");
    expect(out.map((m) => m.item.title)).toEqual([
      "Zeta",
      "Gold",
      "Gold Fund",
      "Sovereign Gold Bond",
      "Nothing",
      "Bangold",
      "Strong hit",
      "Weak hit",
      "Notes hit",
    ]);
    expect(out.map((m) => m.tier)).toEqual([1, 2, 3, 4, 5, 6, 7, 7, 9]);
  });

  it("ranks a typo match as tier 8, between weak terms and notes", () => {
    const list = [
      make("Reliance Industries"),
      make("Other", { notes: "relianse noted" }),
      make("Third", { terms: { weak: ["relianse"] } }),
    ];
    expect(rankHoldings(prepareIndex(list), "relianse").map((m) => [m.item.title, m.tier])).toEqual([
      ["Third", 7],
      ["Reliance Industries", 8],
      ["Other", 9],
    ]);
  });

  it("matches an exact id whatever the spacing or punctuation", () => {
    const list = [make("Infosys", { terms: { ids: ["INE009A01021"] } })];
    for (const q of ["INE009A01021", "ine 009a01021", "INE-009A01021"]) {
      expect(tierOf(list, q, "Infosys"), q).toBe(1);
    }
  });

  it("matches a title however it is punctuated", () => {
    const list = [make("HDFC Bank"), make("Gold & Silver ETF")];
    expect(tierOf(list, "hdfc-bank", "HDFC Bank")).toBe(2);
    expect(tierOf(list, "gold and silver", "Gold & Silver ETF")).toBe(3);
    expect(tierOf(list, "silver", "Gold & Silver ETF")).toBe(4);
  });

  it("counts subtitle and type label as weak terms", () => {
    const list = [
      make("Tata Motors"),
      make("Parag Parikh Flexi", { type: "mf", type_label: "Mutual funds", subtitle: "Direct growth" }),
    ];
    expect(titles(list, "stocks")).toEqual(["Tata Motors"]);
    expect(titles(list, "direct")).toEqual(["Parag Parikh Flexi"]);
    expect(tierOf(list, "mutual", "Parag Parikh Flexi")).toBe(7);
  });

  it("puts strong terms ahead of weak terms inside tier 7", () => {
    const list = [
      make("Weak", { terms: { weak: ["banking"] }, current_value: 9 }),
      make("Strong", { terms: { strong: ["banking"] }, current_value: 1 }),
    ];
    expect(titles(list, "banking")).toEqual(["Strong", "Weak"]);
  });
});

describe("tokens", () => {
  const list = [
    make("HDFC Bank", { terms: { weak: ["liquid fund"] } }),
    make("HDFC Bank Savings"),
    make("ICICI Liquid", { terms: { weak: ["hdfc"] } }),
    make("Liquid Gold"),
  ];

  it("requires every token to match somewhere", () => {
    expect(titles(list, "hdfc liquid")).toEqual(["HDFC Bank", "ICICI Liquid"]);
    expect(titles(list, "liquid gold hdfc")).toEqual([]);
  });

  it("ignores the order of tokens", () => {
    expect(titles(list, "liquid hdfc")).toEqual(["HDFC Bank", "ICICI Liquid"]);
  });
});

describe("one-character queries", () => {
  const list = [
    make("Reliance"),
    make("Tata Rail"),
    make("Bharat"),
    make("Other", { terms: { strong: ["rainbow"], weak: ["rain"] }, notes: "r is here", subtitle: "rx" }),
    make("Ids", { terms: { ids: ["R123"] } }),
  ];

  it("matches only word prefixes and id prefixes", () => {
    expect(titles(list, "r")).toEqual(["Reliance", "Tata Rail", "Ids"]);
  });

  it("does not use typos, substrings or notes", () => {
    expect(titles(list, "h")).toEqual([]);
  });
});

describe("typos", () => {
  const list = [make("Reliance Industries"), make("Infosys")];

  it("finds Reliance from relianse", () => {
    expect(titles(list, "relianse")).toEqual(["Reliance Industries"]);
  });

  it("counts a swap as one edit", () => {
    expect(editDistance("infosys", "infoyss", 2)).toBe(1);
    expect(titles(list, "infoyss")).toEqual(["Infosys"]);
  });

  it("allows one edit up to 7 characters", () => {
    expect(titles(list, "infosis")).toEqual(["Infosys"]);
    expect(titles(list, "infusus")).toEqual([]);
  });

  it("allows two edits from 8 characters", () => {
    expect(titles(list, "relianxx")).toEqual(["Reliance Industries"]);
    expect(titles(list, "relianxxx")).toEqual([]);
  });

  it("ignores typos in 3-character tokens", () => {
    expect(titles(list, "rwl")).toEqual([]);
    expect(titles(list, "ifo")).toEqual([]); // one swap from "ino"/"inf" style words, but too short
  });

  it("only compares against title words, not terms", () => {
    expect(titles([make("Other", { terms: { strong: ["reliance"] } })], "relianse")).toEqual([]);
  });
});

describe("tie-breaks", () => {
  it("prefers the lower sum of per-token tiers", () => {
    const list = [
      make("Fund Zeta", { terms: { weak: ["gold"] }, current_value: 1e9 }),
      make("Gold Fund", { current_value: 1 }),
    ];
    expect(titles(list, "fund gold")).toEqual(["Gold Fund", "Fund Zeta"]);
  });

  it("then prefers active over any other status", () => {
    const list = [
      make("Alpha Matured", { status: "matured", current_value: 1e9 }),
      make("Alpha Closed", { status: "closed", current_value: 1e9 }),
      make("Alpha Active", { status: "active", current_value: 1 }),
    ];
    expect(titles(list, "alpha")[0]).toBe("Alpha Active");
  });

  it("then prefers recently opened, earlier in the list first", () => {
    const a = make("Alpha One", { current_value: 9 });
    const b = make("Alpha Two", { current_value: 5 });
    const c = make("Alpha Three", { current_value: 1 });
    expect(titles([a, b, c], "alpha")).toEqual(["Alpha One", "Alpha Two", "Alpha Three"]);
    expect(titles([a, b, c], "alpha", [`stock:${c.id}`, `stock:${b.id}`])).toEqual([
      "Alpha Three",
      "Alpha Two",
      "Alpha One",
    ]);
  });

  it("recent items only matter inside the same tier", () => {
    const worse = make("Beta Alpha", { current_value: 1 });
    const better = make("Alpha Beta", { current_value: 1 });
    expect(titles([worse, better], "alpha", [`stock:${worse.id}`])).toEqual(["Alpha Beta", "Beta Alpha"]);
  });

  it("then prefers larger value, then title", () => {
    const list = [
      make("Alpha B", { current_value: 5 }),
      make("Alpha A", { current_value: 5 }),
      make("Alpha C", { current_value: 50 }),
    ];
    expect(titles(list, "alpha")).toEqual(["Alpha C", "Alpha A", "Alpha B"]);
  });

  it("never lets a huge value beat a better tier", () => {
    const list = [
      make("Fund Gold", { current_value: 1 }),
      make("Silver", { terms: { weak: ["fund gold"] }, current_value: 1e15 }),
    ];
    expect(titles(list, "gold")).toEqual(["Fund Gold", "Silver"]);
  });
});

describe("empty and odd queries", () => {
  it("returns nothing for a query with no letters or digits", () => {
    const index = prepareIndex([make("Alpha")]);
    expect(rankHoldings(index, "")).toEqual([]);
    expect(rankHoldings(index, " - ")).toEqual([]);
  });
});

describe("highlightRanges", () => {
  it("returns indexes in the original string when & expands to and", () => {
    expect(highlightRanges("Gold & Silver", "silver")).toEqual([[7, 13]]);
    expect(highlightRanges("Gold & Silver", "and")).toEqual([[5, 6]]);
    expect(highlightRanges("Gold & Silver", "gold and silver")).toEqual([
      [0, 4],
      [5, 6],
      [7, 13],
    ]);
  });

  it("maps through diacritics, composed or decomposed", () => {
    expect(highlightRanges("Crédit Suisse", "credit")).toEqual([[0, 6]]);
    expect(highlightRanges("Crédit Suisse", "credit")).toEqual([[0, 7]]);
    expect(highlightRanges("Crédit Suisse", "suisse")).toEqual([[7, 13]]);
  });

  it("matches punctuation-insensitively", () => {
    expect(highlightRanges("HDFC Bank", "hdfc-bank")).toEqual([[0, 4], [5, 9]]);
  });

  it("merges overlapping ranges", () => {
    expect(highlightRanges("Banking", "bank king")).toEqual([[0, 7]]);
    expect(highlightRanges("Gold Gold", "gold gol")).toEqual([[0, 4], [5, 9]]);
  });

  it("highlights every occurrence, but only word starts for one character", () => {
    expect(highlightRanges("Tata Rail", "ta")).toEqual([[0, 4]]);
    expect(highlightRanges("Bharat Rail", "r")).toEqual([[7, 8]]);
  });

  it("highlights the whole word for a typo match", () => {
    expect(highlightRanges("Reliance Industries", "relianse")).toEqual([[0, 8]]);
  });

  it("never goes out of bounds", () => {
    const texts = ["Gold & Silver & Co", "&", "&&", "Æon Café — Ünïcode", "á", "😀 Gold & 😀", "", "---"];
    const queries = ["gold", "and", "&", "a", "cafe unicode", "😀", "silve", "gld co", "aon", ""];
    for (const t of texts) {
      for (const q of queries) {
        for (const [s, e] of highlightRanges(t, q)) {
          expect(s, `${t} / ${q}`).toBeGreaterThanOrEqual(0);
          expect(e, `${t} / ${q}`).toBeLessThanOrEqual(t.length);
          expect(s, `${t} / ${q}`).toBeLessThan(e);
        }
      }
    }
  });
});

describe("title ranges and notes snippet", () => {
  it("returns title ranges on each match", () => {
    const [m] = rankHoldings(prepareIndex([make("Gold & Silver")]), "silver");
    expect(m.titleRanges).toEqual([[7, 13]]);
  });

  const notes =
    "The quick brown fox jumps over the lazy dog while the amazing certificate of deposit matures on the fifteenth of March after the long monsoon season ends";

  it("returns an ellipsised snippet around a notes-only hit", () => {
    const [m] = rankHoldings(prepareIndex([make("Plain", { notes })]), "certificate");
    expect(m.tier).toBe(9);
    const snip = m.notesSnippet!;
    expect(snip.text.startsWith("…")).toBe(true);
    expect(snip.text.endsWith("…")).toBe(true);
    const body = snip.text.slice(1, -1);
    expect(notes.includes(body)).toBe(true);
    expect(body.length).toBeLessThanOrEqual(110);
    const at = notes.indexOf(body);
    // cut on word boundaries
    expect(notes[at - 1]).toBe(" ");
    expect(notes[at + body.length]).toBe(" ");
    expect(snip.ranges).toHaveLength(1);
    const [s, e] = snip.ranges[0];
    expect(snip.text.slice(s, e)).toBe("certificate");
  });

  it("does not add ellipses to short notes", () => {
    const [m] = rankHoldings(prepareIndex([make("Plain", { notes: "Joint with spouse" })]), "spouse");
    expect(m.notesSnippet?.text).toBe("Joint with spouse");
    expect(m.notesSnippet?.ranges).toEqual([[11, 17]]);
  });

  it("has no snippet when a better field matched", () => {
    const list = [
      make("Spouse FD", { notes: "spouse" }),
      make("Other", { terms: { strong: ["spouse"] }, notes: "spouse" }),
    ];
    for (const m of rankHoldings(prepareIndex(list), "spouse")) expect(m.notesSnippet).toBeNull();
  });
});

describe("groupMatches", () => {
  const list = [
    make("Alpha Fund 1", { type: "mf", type_label: "Mutual funds" }),
    make("Alpha Stock 1"),
    make("Alpha Stock 2"),
    make("Alpha Stock 3"),
    make("Zed", { type: "mf", type_label: "Mutual funds", terms: { weak: ["alpha"] } }),
  ];
  const matches = rankHoldings(prepareIndex(list), "alpha");

  it("orders groups by their best match and limits visible rows", () => {
    const groups = groupMatches(matches, { perGroup: 2 });
    expect(groups.map((g) => g.type)).toEqual(["mf", "stock"]);
    expect(groups[0]).toMatchObject({ type_label: "Mutual funds", hiddenCount: 0 });
    expect(groups[0].matches.map((m) => m.item.title)).toEqual(["Alpha Fund 1", "Zed"]);
    expect(groups[1].matches).toHaveLength(2);
    expect(groups[1].hiddenCount).toBe(1);
  });

  it("shows everything for an expanded group", () => {
    const groups = groupMatches(matches, { perGroup: 2, expanded: new Set(["stock"]) });
    expect(groups[1].matches).toHaveLength(3);
    expect(groups[1].hiddenCount).toBe(0);
  });

  it("defaults to five rows per group", () => {
    const many = Array.from({ length: 7 }, (_, i) => make(`Alpha ${i}`));
    const [g] = groupMatches(rankHoldings(prepareIndex(many), "alpha"));
    expect(g.matches).toHaveLength(5);
    expect(g.hiddenCount).toBe(2);
  });
});

import { describe, expect, it } from "vitest";
import { ASSET_CATALOG } from "../asset-catalog";
import { rankStatic, STATIC_ENTRIES } from "./static-entries";

const ids = (query: string) => rankStatic(query).map((m) => m.entry.id);

describe("STATIC_ENTRIES", () => {
  it("has a portfolio tab and an Add entry for every catalog type", () => {
    for (const a of ASSET_CATALOG) {
      const tab = STATIC_ENTRIES.find((e) => e.href === `/portfolio/${a.type}`);
      const add = STATIC_ENTRIES.find((e) => e.href === `/add/${a.type}` && e.title.startsWith("Add"));
      expect(tab?.kind, a.type).toBe("goto");
      expect(tab?.title).toBe(a.title);
      expect(add?.kind, a.type).toBe("action");
      expect(add?.title).toBe(`Add ${a.title}`);
    }
  });

  it("has Dashboard, Recently deleted, the Add gallery and Import CAS", () => {
    const hrefs = STATIC_ENTRIES.map((e) => e.href);
    expect(hrefs).toEqual(expect.arrayContaining(["/dashboard", "/deleted", "/add", "/add/mf"]));
    const cas = STATIC_ENTRIES.find((e) => e.title === "Import CAS");
    expect(cas?.aliases).toEqual(expect.arrayContaining(["cas", "mutual fund import", "statement"]));
  });

  it("has unique ids", () => {
    expect(new Set(STATIC_ENTRIES.map((e) => e.id)).size).toBe(STATIC_ENTRIES.length);
  });
});

describe("rankStatic", () => {
  it("returns nothing for an empty query", () => {
    expect(rankStatic("")).toEqual([]);
    expect(rankStatic("  ")).toEqual([]);
  });

  it("matches shorthand aliases and lists Go to before Add", () => {
    expect(ids("fd").slice(0, 2)).toEqual(["goto-fd", "action-add-fd"]);
    expect(ids("sgb")).toContain("goto-bond");
    expect(ids("epf")).toContain("goto-pf");
    expect(ids("ppf")).toContain("goto-pf");
    expect(ids("vpf")).toContain("goto-pf");
    expect(ids("savings")[0]).toBe("goto-cash");
    expect(ids("crypto")[0]).toBe("goto-other");
    expect(ids("silver")).toContain("goto-gold");
    expect(ids("trash")).toEqual(["goto-deleted"]);
    expect(ids("home")).toEqual(["goto-dashboard"]);
    expect(ids("net worth")).toEqual(["goto-dashboard"]);
  });

  it("counts an alias prefix like a title prefix", () => {
    const [first] = rankStatic("cas");
    expect(first.entry.id).toBe("action-import-cas");
    expect(first.tier).toBe(3);
    expect(ids("statem")).toEqual(["action-import-cas"]);
  });

  it("ranks a title prefix above a word or substring hit", () => {
    const out = rankStatic("dep");
    expect(out.map((m) => m.tier)).toEqual([...out.map((m) => m.tier)].sort((a, b) => a - b));
    expect(out[0].entry.title).toBe("Fixed deposit");
  });

  it("ANDs tokens and finds Add entries by title and alias", () => {
    expect(ids("add fd")).toEqual(["action-add-fd"]);
    expect(ids("add stocks")).toEqual(["action-add-stock"]);
  });

  it("tolerates a typo and reports title ranges", () => {
    const [first] = rankStatic("dashbord");
    expect(first.entry.id).toBe("goto-dashboard");
    expect(first.tier).toBe(8);
    expect(first.titleRanges).toEqual([[0, 9]]);
    expect(rankStatic("dash")[0].titleRanges).toEqual([[0, 4]]);
  });
});

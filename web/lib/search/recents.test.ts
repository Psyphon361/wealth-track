import { describe, expect, it } from "vitest";
import { EMPTY_RECENTS, MAX_RECENTS, parseRecents, pushRecent, removeRecent } from "./recents";

describe("pushRecent", () => {
  it("puts the newest first", () => {
    expect(pushRecent(["b", "a"], "c")).toEqual(["c", "b", "a"]);
  });

  it("moves a repeat to the front and keeps the newest spelling", () => {
    expect(pushRecent(["hdfc", "sbi", "gold"], "SBI")).toEqual(["SBI", "hdfc", "gold"]);
  });

  it("trims the value and ignores blank ones", () => {
    expect(pushRecent(["a"], "  b  ")).toEqual(["b", "a"]);
    expect(pushRecent(["a"], "   ")).toEqual(["a"]);
  });

  it("keeps at most 8", () => {
    const full = Array.from({ length: MAX_RECENTS }, (_, i) => `q${i}`);
    const next = pushRecent(full, "new");
    expect(next).toHaveLength(MAX_RECENTS);
    expect(next[0]).toBe("new");
    expect(next).not.toContain("q7");
  });

  it("does not change the input list", () => {
    const list = ["a", "b"];
    pushRecent(list, "c");
    expect(list).toEqual(["a", "b"]);
  });
});

describe("removeRecent", () => {
  it("removes case-insensitively", () => {
    expect(removeRecent(["Gold", "sbi"], "gold")).toEqual(["sbi"]);
  });

  it("leaves the list alone when the value is absent", () => {
    expect(removeRecent(["a"], "z")).toEqual(["a"]);
  });
});

describe("parseRecents", () => {
  it("reads a valid value", () => {
    expect(parseRecents('{"queries":["hdfc"],"opened":["stock:12","fd:3"]}')).toEqual({
      queries: ["hdfc"],
      opened: ["stock:12", "fd:3"],
    });
  });

  it("gives empty lists for missing, broken or wrongly shaped text", () => {
    expect(parseRecents(null)).toEqual(EMPTY_RECENTS);
    expect(parseRecents("")).toEqual(EMPTY_RECENTS);
    expect(parseRecents("{not json")).toEqual(EMPTY_RECENTS);
    expect(parseRecents("[]")).toEqual(EMPTY_RECENTS);
    expect(parseRecents('"text"')).toEqual(EMPTY_RECENTS);
    expect(parseRecents("null")).toEqual(EMPTY_RECENTS);
  });

  it("keeps a good list when the other one is malformed", () => {
    expect(parseRecents('{"queries":"oops","opened":["fd:1"]}')).toEqual({
      queries: [],
      opened: ["fd:1"],
    });
  });

  it("drops non-strings, blanks and case-insensitive repeats, and caps at 8", () => {
    const many = Array.from({ length: 12 }, (_, i) => `q${i}`);
    const parsed = parseRecents(JSON.stringify({ queries: [1, "", "  ", "A", "a", ...many], opened: [] }));
    expect(parsed.queries[0]).toBe("A");
    expect(parsed.queries).toHaveLength(MAX_RECENTS);
    expect(parsed.queries.filter((q) => q.toLowerCase() === "a")).toHaveLength(1);
  });
});

import { describe, expect, it } from "vitest";
import { compact, normalize, normalizeMapped, tokenize } from "./normalize";

describe("normalize", () => {
  it("lowercases, strips diacritics and collapses punctuation and spaces", () => {
    expect(normalize("  HDFC-Bank,  Ltd. ")).toBe("hdfc bank ltd");
    expect(normalize("Crédit Suisse")).toBe("credit suisse");
    expect(normalize("Crédit")).toBe("credit");
  });

  it("turns & into and", () => {
    expect(normalize("Gold & Silver")).toBe("gold and silver");
    expect(normalize("S&P 500")).toBe("s and p 500");
  });

  it("makes hyphenated and spaced forms equal", () => {
    expect(normalize("hdfc-bank")).toBe(normalize("HDFC Bank"));
  });

  it("tokenizes, and gives nothing for punctuation only", () => {
    expect(tokenize("Gold & Silver")).toEqual(["gold", "and", "silver"]);
    expect(tokenize(" -- ")).toEqual([]);
  });

  it("compacts to a form without spaces", () => {
    expect(compact("INE 002A01018")).toBe(compact("INE002A01018"));
    expect(compact("ine-002a01018")).toBe("ine002a01018");
  });

  it("maps every normalised unit back to its original span", () => {
    const n = normalizeMapped("Gold & Silver");
    expect(n.text).toBe("gold and silver");
    expect(n.starts).toHaveLength(n.text.length);
    expect(n.ends).toHaveLength(n.text.length);
    // "and" comes from the single "&" at index 5
    expect([n.starts[5], n.ends[5]]).toEqual([5, 6]);
    expect([n.starts[7], n.ends[7]]).toEqual([5, 6]);
  });
});

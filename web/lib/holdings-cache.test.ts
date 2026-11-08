import { describe, expect, it } from "vitest";
import { staleTypes } from "./holdings-cache";

describe("staleTypes", () => {
  it("adds cash when paid from is involved", () => {
    expect(staleTypes("fd", true)).toEqual(["fd", "cash"]);
  });
  it("is only the own type without paid from", () => {
    expect(staleTypes("stock", false)).toEqual(["stock"]);
  });
  it("does not duplicate cash", () => {
    expect(staleTypes("cash", true)).toEqual(["cash"]);
  });
});

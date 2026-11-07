import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { peekReinvest, setReinvest, takeReinvest, type ReinvestPrefill } from "./reinvest";

function memoryStorage() {
  const m = new Map<string, string>();
  return {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => void m.set(k, v),
    removeItem: (k: string) => void m.delete(k),
  };
}

const prefill: ReinvestPrefill = {
  type: "fd",
  amount: 107186,
  date: "2026-11-01",
  cash_id: 4,
  cash_name: "HDFC Savings",
  from_exit_id: 9,
};

describe("reinvest handoff", () => {
  beforeEach(() => {
    vi.stubGlobal("sessionStorage", memoryStorage());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns the prefill once and clears it", () => {
    setReinvest(prefill);
    expect(takeReinvest("fd")).toEqual(prefill);
    expect(takeReinvest("fd")).toBeNull();
  });

  it("keeps the prefill when the type does not match", () => {
    setReinvest(prefill);
    expect(takeReinvest("mf")).toBeNull();
    expect(takeReinvest("fd")).toEqual(prefill);
  });

  it("hands a wildcard prefill to whichever type asks, with that type", () => {
    setReinvest({ ...prefill, type: "*" });
    expect(takeReinvest("mf")).toEqual({ ...prefill, type: "mf" });
    expect(takeReinvest("mf")).toBeNull();
  });

  it("peeks without clearing", () => {
    setReinvest({ ...prefill, type: "*" });
    expect(peekReinvest()).toEqual({ ...prefill, type: "*" });
    expect(peekReinvest()).not.toBeNull();
    expect(takeReinvest("gold")).not.toBeNull();
    expect(peekReinvest()).toBeNull();
  });

  it("ignores malformed stored data", () => {
    sessionStorage.setItem("wt.reinvest", "{not json");
    expect(takeReinvest("fd")).toBeNull();
    sessionStorage.setItem("wt.reinvest", JSON.stringify({ type: "fd" }));
    expect(takeReinvest("fd")).toBeNull();
  });

  it("does not throw when storage is unavailable", () => {
    vi.stubGlobal("sessionStorage", {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {
        throw new Error("denied");
      },
      removeItem: () => {
        throw new Error("denied");
      },
    });
    expect(() => setReinvest(prefill)).not.toThrow();
    expect(takeReinvest("fd")).toBeNull();
  });
});

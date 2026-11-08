import { describe, expect, it } from "vitest";
import { NAME_MAX_ERROR, NAME_REQUIRED_ERROR, cleanName, initials } from "./profile";

describe("initials", () => {
  it("uses first and last words", () => {
    expect(initials("Tanish Sharma", "a@b.c")).toBe("TS");
    expect(initials("tanish kumar sharma", "a@b.c")).toBe("TS");
  });
  it("handles one word and extra spaces", () => {
    expect(initials("Tanish", "a@b.c")).toBe("T");
    expect(initials("  tanish   sharma  ", "a@b.c")).toBe("TS");
  });
  it("falls back to the email", () => {
    expect(initials(null, "zed@b.c")).toBe("Z");
    expect(initials("   ", "zed@b.c")).toBe("Z");
    expect(initials(undefined, "zed@b.c")).toBe("Z");
  });
  it("keeps non-Latin characters whole", () => {
    expect(initials("आर्य शर्मा", "a@b.c")).toBe("आश");
    expect(initials("😀 Smith", "a@b.c")).toBe("😀S");
  });
});

describe("cleanName", () => {
  it("trims and collapses spaces", () => {
    expect(cleanName("  Tanish   Sharma ")).toEqual({ name: "Tanish Sharma", error: null });
  });
  it("rejects blank", () => {
    expect(cleanName("   ").error).toBe(NAME_REQUIRED_ERROR);
  });
  it("rejects more than 80 characters", () => {
    expect(cleanName("a".repeat(81)).error).toBe(NAME_MAX_ERROR);
    expect(cleanName("a".repeat(80)).error).toBeNull();
  });
});

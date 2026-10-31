import { describe, expect, it } from "vitest";
import { formatINRCompact } from "./format";

describe("formatINRCompact", () => {
  it("uses Indian units", () => {
    expect(formatINRCompact(0)).toBe("₹0");
    expect(formatINRCompact(950)).toBe("₹950");
    expect(formatINRCompact(12000)).toBe("₹12K");
    expect(formatINRCompact(1240000)).toBe("₹12.4L");
    expect(formatINRCompact(10000000)).toBe("₹1Cr");
    expect(formatINRCompact(12500000)).toBe("₹1.3Cr");
  });
  it("keeps the sign", () => {
    expect(formatINRCompact(-250000)).toBe("-₹2.5L");
  });
});

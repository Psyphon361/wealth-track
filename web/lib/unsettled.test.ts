import { describe, expect, it } from "vitest";
import {
  maturedOnText,
  settleHref,
  unsettledTitle,
  unsettledToggleLabel,
  visibleUnsettled,
} from "./unsettled";
import type { UnsettledItem } from "./types";

const item = (id: number): UnsettledItem => ({
  type: "fd",
  id,
  name: `FD ${id}`,
  maturity_date: "2027-01-07",
  amount: 100,
});

describe("unsettledTitle", () => {
  it("uses the plural for several holdings", () => {
    expect(unsettledTitle(2, 310000)).toBe(
      "2 matured holdings to settle · ₹3,10,000",
    );
  });
  it("uses the singular for one holding", () => {
    expect(unsettledTitle(1, 50000)).toBe("1 matured holding to settle · ₹50,000");
  });
});

describe("maturedOnText", () => {
  it("formats the date", () => {
    expect(maturedOnText("2027-01-07")).toBe("Matured 7 Jan 2027");
  });
});

describe("visibleUnsettled and the toggle", () => {
  const five = [1, 2, 3, 4, 5].map(item);
  it("shows three rows collapsed and all when expanded", () => {
    expect(visibleUnsettled(five, false)).toHaveLength(3);
    expect(visibleUnsettled(five, true)).toHaveLength(5);
  });
  it("labels the toggle", () => {
    expect(unsettledToggleLabel(5, false)).toBe("Show All 5");
    expect(unsettledToggleLabel(5, true)).toBe("Show Less");
  });
  it("has no toggle when three or fewer rows", () => {
    expect(unsettledToggleLabel(3, false)).toBeNull();
    expect(unsettledToggleLabel(1, true)).toBeNull();
  });
});

describe("settleHref", () => {
  it("opens the settle dialog on the details page", () => {
    expect(settleHref({ type: "bond", id: 7 })).toBe("/portfolio/bond/7?settle=1");
  });
});

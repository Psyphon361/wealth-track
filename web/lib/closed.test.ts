import { describe, expect, it } from "vitest";
import { closedOnDate, closedStatus, isClosedStatusParam, realisedGain, receivedAmount } from "./closed";
import type { ExitSummary } from "./types";

const exit: ExitSummary = {
  id: 1,
  kind: "sale",
  date: "2027-01-07",
  quantity: 10,
  amount: 1250.5,
  cost: 1000.1,
  charges: 0,
  destination: "none",
  cash_holding_id: null,
  new_holding_id: null,
  new_asset_type: null,
  reinvested: 0,
  left_in_account: null,
};

describe("closedStatus", () => {
  it("reads Sold for a sold holding", () => {
    expect(closedStatus({ status: "sold", settled: true })).toEqual({
      label: "Sold",
      attention: false,
    });
  });
  it("reads Matured · Settled once the payout is recorded", () => {
    expect(closedStatus({ status: "matured", settled: true })).toEqual({
      label: "Matured · Settled",
      attention: false,
    });
  });
  it("flags an unsettled maturity", () => {
    expect(closedStatus({ status: "matured", settled: false })).toEqual({
      label: "Matured · Not Settled",
      attention: true,
    });
  });
});

describe("receivedAmount", () => {
  it("uses the recorded exit amount", () => {
    expect(receivedAmount({ exit, maturity_amount: 99 })).toBe(1250.5);
  });
  it("falls back to the maturity amount when unsettled", () => {
    expect(receivedAmount({ exit: null, maturity_amount: 310000 })).toBe(310000);
  });
  it("is null when neither is known", () => {
    expect(receivedAmount({ exit: null, maturity_amount: null })).toBeNull();
  });
});

describe("realisedGain", () => {
  it("is amount minus cost, rounded to paise", () => {
    expect(realisedGain({ exit })).toBe(250.4);
  });
  it("is negative for a loss", () => {
    expect(realisedGain({ exit: { ...exit, amount: 900, cost: 1000 } })).toBe(-100);
  });
  it("is null until the exit is recorded", () => {
    expect(realisedGain({ exit: null })).toBeNull();
  });
});

describe("closedOnDate", () => {
  it("prefers the exit date", () => {
    expect(
      closedOnDate({ exit, closed_on: "2027-01-05", maturity_date: "2027-01-01" }),
    ).toBe("2027-01-07");
  });
  it("falls back to closed_on", () => {
    expect(
      closedOnDate({ exit: null, closed_on: "2027-01-05", maturity_date: "2027-01-01" }),
    ).toBe("2027-01-05");
  });
  it("falls back to the maturity date for an unsettled maturity", () => {
    expect(
      closedOnDate({ exit: null, closed_on: null, maturity_date: "2027-01-01" }),
    ).toBe("2027-01-01");
  });
  it("is null when no date is known", () => {
    expect(closedOnDate({ exit: null, closed_on: null, maturity_date: null })).toBeNull();
    expect(closedOnDate({ exit: null, closed_on: null })).toBeNull();
  });
});

describe("isClosedStatusParam", () => {
  it("accepts closed and the old matured value", () => {
    expect(isClosedStatusParam("closed")).toBe(true);
    expect(isClosedStatusParam("matured")).toBe(true);
  });
  it("rejects anything else", () => {
    expect(isClosedStatusParam("active")).toBe(false);
    expect(isClosedStatusParam(null)).toBe(false);
  });
});

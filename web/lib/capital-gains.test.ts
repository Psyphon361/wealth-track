import { describe, expect, it } from "vitest";
import { leftToPay } from "./tax";
import {
  bondInterestLeftToPay,
  sourceText,
  type CapitalGainsSale,
  bucketNotes,
  capitalGainsPath,
  estimatedTax,
  flagText,
  footnotes,
  heldBetween,
  rateText,
  saleTermSummary,
  termText,
  type CapitalGainsLot,
} from "./capital-gains";

const lot = (over: Partial<CapitalGainsLot>): CapitalGainsLot => ({
  bought_on: "2024-01-01",
  quantity: 1,
  cost: 100,
  proceeds: 120,
  gain: 20,
  days_held: 100,
  term: "short",
  bucket: "equity_st",
  ...over,
});

describe("capitalGainsPath", () => {
  it("adds the fy only when given", () => {
    expect(capitalGainsPath()).toBe("/analytics/capital-gains");
    expect(capitalGainsPath(2025)).toBe("/analytics/capital-gains?fy=2025");
  });
});

describe("estimatedTax", () => {
  it("adds slab gains at the slab and 4% cess, in whole rupees", () => {
    expect(estimatedTax({ fixed_rate_tax: 1000, slab_gains: 10000 }, 30)).toBe(4160);
    expect(estimatedTax({ fixed_rate_tax: 1001, slab_gains: 0 }, null)).toBe(1041);
  });
  it("is null when slab gains exist and no slab is chosen", () => {
    expect(estimatedTax({ fixed_rate_tax: 1000, slab_gains: 500 }, null)).toBeNull();
  });
  it("ignores the slab when there are no slab gains", () => {
    expect(estimatedTax({ fixed_rate_tax: 500, slab_gains: 0 }, 30)).toBe(520);
    expect(estimatedTax({ fixed_rate_tax: 0, slab_gains: 0 }, null)).toBe(0);
  });
  it("handles a 0% slab", () => {
    expect(estimatedTax({ fixed_rate_tax: 100, slab_gains: 9000 }, 0)).toBe(104);
  });
});

describe("heldBetween", () => {
  it("counts whole calendar months from the dates", () => {
    expect(heldBetween("2025-01-01", "2025-01-21")).toBe("20 days");
    expect(heldBetween("2025-01-01", "2025-01-02")).toBe("1 day");
    expect(heldBetween("2024-01-15", "2024-09-15")).toBe("8 mo");
    expect(heldBetween("2023-03-10", "2024-03-10")).toBe("1 yr");
    expect(heldBetween("2023-03-10", "2024-06-10")).toBe("1 yr 3 mo");
    expect(heldBetween("2022-03-10", "2024-04-10")).toBe("2 yrs 1 mo");
  });
  it("does not count a month that is not complete", () => {
    expect(heldBetween("2024-01-31", "2024-02-29")).toBe("29 days");
    expect(heldBetween("2024-01-20", "2024-03-10")).toBe("1 mo");
  });
  it("is Unknown without a purchase date", () => {
    expect(heldBetween(null, "2025-01-01")).toBe("Unknown");
  });
});

describe("termText", () => {
  it("labels each term", () => {
    expect(termText("short")).toBe("Short Term");
    expect(termText("long")).toBe("Long Term");
    expect(termText("flat")).toBe("Flat 30%");
    expect(termText(null)).toBe("Not Counted");
  });
});

describe("saleTermSummary", () => {
  it("returns one term when lots agree", () => {
    expect(saleTermSummary({ lots: [lot({}), lot({})] })).toBe("Short Term");
    expect(
      saleTermSummary({ lots: [lot({ term: "long", bucket: "equity_lt" })] }),
    ).toBe("Long Term");
  });
  it("returns the mixed label when lots differ", () => {
    expect(
      saleTermSummary({ lots: [lot({}), lot({ term: "long", bucket: "equity_lt" })] }),
    ).toBe("Part Short, Part Long Term");
  });
  it("is Not Counted when no lot has a bucket", () => {
    expect(
      saleTermSummary({ lots: [lot({ bucket: null, term: null }), lot({ bucket: null })] }),
    ).toBe("Not Counted");
    expect(saleTermSummary({ lots: [] })).toBe("Not Counted");
  });
});

describe("flagText", () => {
  it("gives the sentence for each flag", () => {
    expect(flagText("grandfathering")).toBe(
      "Bought before 1 Feb 2018: your cost may be higher under the 31 Jan 2018 price rule. Not applied here.",
    );
    expect(flagText("no_purchase_date")).toContain("No purchase date");
    expect(flagText("guessed_class")).toBe("Tax type guessed from the name. Check it.");
    expect(flagText("old_rules")).toContain("23 Jul 2024");
    expect(flagText("multi_asset")).toContain("Treated as non-equity.");
    expect(flagText("estimated")).toBe("Estimated: counted at face value on the repayment date.");
  });
});

describe("sourceText", () => {
  it("labels each source", () => {
    expect(sourceText("maturity")).toBe("Repaid At Maturity");
    expect(sourceText("planned_sale")).toBe("Planned Sale");
    expect(sourceText("sale")).toBe("Sold");
  });
});

describe("bondInterestLeftToPay", () => {
  const bi = { interest_projected: 10000, tds_estimate: 1000 };
  it("matches the Interest & TDS tab: tax at slab with cess minus TDS", () => {
    expect(bondInterestLeftToPay(bi, 30)).toBe(leftToPay(10000, 1000, 30));
    expect(bondInterestLeftToPay(bi, 30)).toBe(2120);
  });
  it("is negative for a refund and null without a slab", () => {
    expect(bondInterestLeftToPay({ interest_projected: 10000, tds_estimate: 2000 }, 5)).toBe(-1480);
    expect(bondInterestLeftToPay(bi, null)).toBeNull();
  });
});

describe("rateText", () => {
  it("shows the slab or the rate", () => {
    expect(rateText({ rate: null })).toBe("Your Slab");
    expect(rateText({ rate: 20 })).toBe("20%");
    expect(rateText({ rate: 12.5 })).toBe("12.5%");
  });
});

describe("bucketNotes", () => {
  it("is empty with no exemption or set-off", () => {
    expect(bucketNotes({ set_off: 0, exemption: 0 }, 2025)).toEqual({ short: "", long: "" });
  });
  it("explains the exemption with the limit for the year", () => {
    expect(bucketNotes({ set_off: 0, exemption: 485 }, 2025).short).toBe("₹485 tax-free");
    expect(bucketNotes({ set_off: 0, exemption: 485 }, 2025).long).toBe(
      "₹485 of this is tax-free: under Section 112A, the first ₹1.25 lakh of equity long-term gains each year is exempt, in both the old and new tax regimes.",
    );
    expect(bucketNotes({ set_off: 0, exemption: 485 }, 2023).long).toContain("₹1 lakh");
  });
  it("explains set-off", () => {
    expect(bucketNotes({ set_off: 1000, exemption: 485 }, 2025).short).toBe(
      "₹485 tax-free · ₹1,000 offset by losses",
    );
  });
});

describe("footnotes", () => {
  const base = {
    excluded: { bonds_no_face: 0, no_purchase_date: 0, old_rules: 0 },
    tax_free: { total: 0, items: [] },
    sales: [] as CapitalGainsSale[],
    expected: [] as CapitalGainsSale[],
  };
  const sale = (source: CapitalGainsSale["source"]): CapitalGainsSale => ({
    exit_id: null,
    source,
    estimated: source !== "sale",
    asset_type: "bond",
    holding_id: 1,
    name: "B",
    sold_on: "2026-12-01",
    proceeds: 100,
    cost: 90,
    gain: 10,
    flags: [],
    lots: [],
  });
  it("always has the two standing sentences", () => {
    expect(footnotes(base)).toEqual([
      "Losses are set off within the year only; carrying them forward isn't tracked.",
      "Surcharge and the 87A rebate are ignored; 4% cess is added.",
    ]);
  });
  it("adds exclusions with correct singular and plural", () => {
    const one = footnotes({
      ...base,
      excluded: { bonds_no_face: 1, no_purchase_date: 1, old_rules: 1 },
    });
    expect(one).toContain("1 bond without a face value isn't included.");
    expect(one).toContain("1 sale isn't counted: no purchase date.");
    expect(one.some((s) => s.startsWith("1 sale isn't counted: sold before"))).toBe(true);
    const many = footnotes({
      ...base,
      excluded: { bonds_no_face: 3, no_purchase_date: 2, old_rules: 0 },
    });
    expect(many).toContain("3 bonds without a face value aren't included.");
    expect(many).toContain("2 sales aren't counted: no purchase date.");
    expect(many).toHaveLength(4);
  });
  it("adds the face value sentence only for maturity or planned sales", () => {
    const text = "Bonds are counted at face value when they're repaid or sold as planned";
    expect(footnotes({ ...base, sales: [sale("sale")] }).some((s) => s.startsWith(text))).toBe(false);
    expect(footnotes({ ...base, sales: [sale("maturity")] }).some((s) => s.startsWith(text))).toBe(true);
    expect(footnotes({ ...base, expected: [sale("planned_sale")] }).some((s) => s.startsWith(text))).toBe(true);
  });
  it("adds the tax-free sentence in Indian formatting", () => {
    const notes = footnotes({ ...base, tax_free: { total: 260970, items: [] } });
    expect(notes[notes.length - 1]).toBe(
      "₹2,60,970 from Sovereign Gold Bonds redeemed at maturity is tax-free.",
    );
  });
});

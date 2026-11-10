import { describe, expect, it } from "vitest";
import { xirrKpi, xirrStartDate } from "./xirr";

describe("xirrKpi", () => {
  it("hides null, undefined and non-finite", () => {
    expect(xirrKpi({ xirr: null })).toBeNull();
    expect(xirrKpi({})).toBeNull();
    expect(xirrKpi({ xirr: Number.NaN })).toBeNull();
  });
  it("keeps zero and negatives", () => {
    expect(xirrKpi({ xirr: 0 }, "2024-01-01")).toEqual({ value: 0, startDate: "2024-01-01" });
    expect(xirrKpi({ xirr: -3.2 })).toEqual({ value: -3.2, startDate: null });
  });
});

describe("xirrStartDate", () => {
  it("prefers start_date, then purchase_date, then buy_date", () => {
    expect(xirrStartDate({ start_date: "2023-01-01", purchase_date: "2024-01-01" })).toBe("2023-01-01");
    expect(xirrStartDate({ purchase_date: "2024-01-01" })).toBe("2024-01-01");
    expect(xirrStartDate({ buy_date: "2022-05-05" })).toBe("2022-05-05");
    expect(xirrStartDate({ name: "x" })).toBeNull();
  });
});

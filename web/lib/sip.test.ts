import { describe, expect, it } from "vitest";
import {
  actionPath,
  amountText,
  availableActions,
  countdownText,
  dayOptionLabel,
  filterSips,
  instalmentsText,
  isSoldHolding,
  monthlyTotal,
  platformLabel,
  shortDate,
  sipSummary,
  sortSips,
  summaryLine,
  nextText,
  ordinal,
  pastDueDates,
  pastInstalments,
  pastQuestion,
  scheduleText,
  showMoreLabel,
  sinceText,
  transactionLabel,
} from "./sip";
import type { Sip } from "./types";

function sip(over: Partial<Sip> = {}): Sip {
  return {
    id: 1,
    mutual_fund_id: 10,
    scheme_code: 120716,
    fund_name: "UTI Nifty 50 Index Fund",
    platform: "Groww",
    amount: 5000,
    day_of_month: 5,
    start_date: "2026-01-05",
    end_date: null,
    status: "active",
    next_date: "2026-12-05",
    skipped_dates: [],
    instalments_added: 11,
    invested_via_sip: 55000,
    ...over,
  };
}

describe("ordinal and day labels", () => {
  it("handles the suffix rules", () => {
    expect(ordinal(1)).toBe("1st");
    expect(ordinal(2)).toBe("2nd");
    expect(ordinal(3)).toBe("3rd");
    expect(ordinal(4)).toBe("4th");
    expect(ordinal(11)).toBe("11th");
    expect(ordinal(12)).toBe("12th");
    expect(ordinal(13)).toBe("13th");
    expect(ordinal(21)).toBe("21st");
    expect(ordinal(22)).toBe("22nd");
    expect(ordinal(23)).toBe("23rd");
    expect(ordinal(28)).toBe("28th");
  });

  it("labels the day options in Title Case", () => {
    expect(dayOptionLabel(5)).toBe("5th of Every Month");
    expect(dayOptionLabel(28)).toBe("28th of Every Month");
  });
});

describe("schedule text", () => {
  it("drops .00 from whole amounts and keeps paise", () => {
    expect(amountText(5000)).toBe("₹5,000");
    expect(amountText(100000)).toBe("₹1,00,000");
    expect(amountText(2500.5)).toBe("₹2,500.50");
  });

  it("describes the schedule and the start month", () => {
    expect(scheduleText(sip())).toBe("₹5,000 on the 5th");
    expect(sinceText(sip())).toBe("₹5,000 on the 5th of every month · since Jan 2026");
  });
});

describe("past instalments", () => {
  it("lists due dates from the start date to today, inclusive", () => {
    expect(pastDueDates("2026-01-05", 5, "2026-04-05")).toEqual([
      "2026-01-05",
      "2026-02-05",
      "2026-03-05",
      "2026-04-05",
    ]);
  });

  it("starts the month after when the start date is past the chosen day", () => {
    expect(pastDueDates("2026-01-06", 5, "2026-03-31")).toEqual(["2026-02-05", "2026-03-05"]);
  });

  it("counts a due date that falls on the start date and one on today", () => {
    expect(pastDueDates("2026-11-05", 5, "2026-11-05")).toEqual(["2026-11-05"]);
  });

  it("is empty when today is before the first due date", () => {
    expect(pastDueDates("2026-11-06", 5, "2026-11-20")).toEqual([]);
    expect(pastDueDates("2026-11-20", 5, "2026-11-20")).toEqual([]);
  });

  it("handles day 28 across February and the month end", () => {
    expect(pastDueDates("2026-01-31", 28, "2026-04-30")).toEqual(["2026-02-28", "2026-03-28", "2026-04-28"]);
    expect(pastDueDates("2026-01-28", 28, "2026-03-27")).toEqual(["2026-01-28", "2026-02-28"]);
  });

  it("crosses the year end", () => {
    expect(pastDueDates("2025-11-10", 10, "2026-02-10")).toEqual([
      "2025-11-10",
      "2025-12-10",
      "2026-01-10",
      "2026-02-10",
    ]);
    expect(pastDueDates("2025-12-20", 5, "2026-02-10")).toEqual(["2026-01-05", "2026-02-05"]);
  });

  it("rejects an invalid day or date", () => {
    expect(pastDueDates("2026-01-01", 29, "2026-06-01")).toEqual([]);
    expect(pastDueDates("2026-01-01", 0, "2026-06-01")).toEqual([]);
    expect(pastDueDates("", 5, "2026-06-01")).toEqual([]);
  });

  it("gives the count and the months", () => {
    expect(pastInstalments("2026-01-05", 5, "2026-10-20")).toEqual({
      count: 10,
      range: "Jan 2026 – Oct 2026",
    });
    expect(pastInstalments("2026-03-01", 5, "2026-03-20")).toEqual({ count: 1, range: "Mar 2026" });
    expect(pastInstalments("2026-11-06", 5, "2026-11-20")).toEqual({ count: 0, range: "" });
  });

  it("builds the question only for a past start date with instalments", () => {
    expect(pastQuestion("2026-01-05", 5, "2026-10-20")).toBe(
      "Add the 10 past instalments (Jan 2026 – Oct 2026) to your total?",
    );
    expect(pastQuestion("2026-03-01", 5, "2026-03-20")).toBe(
      "Add the 1 past instalment (Mar 2026) to your total?",
    );
    expect(pastQuestion("2026-10-20", 5, "2026-10-20")).toBeNull();
    expect(pastQuestion("2026-11-20", 5, "2026-10-20")).toBeNull();
    expect(pastQuestion("2026-11-06", 5, "2026-11-20")).toBeNull();
    expect(pastQuestion("", 5, "2026-11-20")).toBeNull();
  });
});

describe("next-instalment text", () => {
  it("shows the next date", () => {
    expect(nextText(sip())).toBe("Next 5 Dec 2026");
  });

  it("says Skipping when the next instalment is skipped", () => {
    expect(nextText(sip({ skipped_dates: ["2026-12-05"] }))).toBe("Skipping 5 Dec 2026");
  });

  it("ignores a skipped date that is not the next one", () => {
    expect(nextText(sip({ skipped_dates: ["2027-01-05"] }))).toBe("Next 5 Dec 2026");
  });

  it("covers paused, cancelled and finished SIPs", () => {
    expect(nextText(sip({ status: "paused", next_date: null }))).toBe("Paused");
    expect(nextText(sip({ status: "stopped", next_date: null }))).toBe("Cancelled");
    expect(nextText(sip({ next_date: null }))).toBe("No upcoming instalment");
  });
});

describe("instalments text", () => {
  it("pluralises and formats the invested amount", () => {
    expect(instalmentsText(sip())).toBe("11 instalments · ₹55,000 invested");
    expect(instalmentsText(sip({ instalments_added: 1, invested_via_sip: 5000 }))).toBe(
      "1 instalment · ₹5,000 invested",
    );
    expect(instalmentsText(sip({ instalments_added: 0, invested_via_sip: 0 }))).toBe(
      "No instalments yet",
    );
  });
});

describe("grouping and totals", () => {
  const list = [
    sip({ id: 1, fund_name: "Zeta Fund", status: "stopped", next_date: null }),
    sip({ id: 2, fund_name: "beta fund", status: "active", amount: 2500.5 }),
    sip({ id: 3, fund_name: "Alpha Fund", status: "paused", next_date: null, amount: 9999 }),
    sip({ id: 4, fund_name: "Alpha Fund", status: "active", amount: 1000 }),
  ];

  it("orders by status, then next date, then fund name by default", () => {
    const withDates = [
      list[0],
      { ...list[1], next_date: "2026-12-20" },
      list[2],
      { ...list[3], next_date: "2026-12-02" },
    ];
    expect(sortSips(withDates, "status", false).map((s) => s.id)).toEqual([4, 2, 3, 1]);
  });

  it("sorts by fund name, amount and instalments in either direction", () => {
    expect(sortSips(list, "fund_name", false).map((s) => s.id)).toEqual([4, 3, 2, 1]);
    expect(sortSips(list, "fund_name", true).map((s) => s.id)).toEqual([1, 2, 4, 3]);
    expect(sortSips(list, "amount", true).map((s) => s.id)).toEqual([3, 1, 2, 4]);
    expect(
      sortSips(
        [sip({ id: 1, instalments_added: 3 }), sip({ id: 2, instalments_added: 9 })],
        "instalments_added",
        true,
      ).map((s) => s.id),
    ).toEqual([2, 1]);
  });

  it("keeps SIPs without a next date last when sorting by next date", () => {
    const l = [
      sip({ id: 1, next_date: null, status: "paused" }),
      sip({ id: 2, next_date: "2026-12-20" }),
      sip({ id: 3, next_date: "2026-12-02" }),
    ];
    expect(sortSips(l, "next_date", false).map((s) => s.id)).toEqual([3, 2, 1]);
    expect(sortSips(l, "next_date", true).map((s) => s.id)).toEqual([2, 3, 1]);
  });

  it("does not change the list it sorts", () => {
    const copy = [...list];
    sortSips(list, "amount", false);
    expect(list).toEqual(copy);
  });

  it("filters by fund or platform text and by status", () => {
    const l = [
      sip({ id: 1, fund_name: "Parag Parikh Flexi Cap", platform: "GROWW" }),
      sip({ id: 2, fund_name: "UTI Nifty 50", platform: "Kuvera", status: "paused" }),
      sip({ id: 3, fund_name: "HDFC Mid Cap", platform: "Kuvera", status: "stopped" }),
    ];
    expect(filterSips(l, "", []).map((s) => s.id)).toEqual([1, 2, 3]);
    expect(filterSips(l, "  parag ", []).map((s) => s.id)).toEqual([1]);
    expect(filterSips(l, "groww", []).map((s) => s.id)).toEqual([1]);
    expect(filterSips(l, "kuvera", []).map((s) => s.id)).toEqual([2, 3]);
    expect(filterSips(l, "", ["paused", "stopped"]).map((s) => s.id)).toEqual([2, 3]);
    expect(filterSips(l, "kuvera", ["paused"]).map((s) => s.id)).toEqual([2]);
    expect(filterSips(l, "zzz", [])).toEqual([]);
  });

  it("totals only the active SIPs", () => {
    expect(monthlyTotal(list)).toBe(3500.5);
    expect(monthlyTotal([list[0], list[2]])).toBe(0);
    expect(monthlyTotal([sip({ amount: 0.1 }), sip({ amount: 0.2 })])).toBe(0.3);
  });
});

describe("platform label", () => {
  it("title-cases all-caps or all-lowercase names and keeps mixed case", () => {
    expect(platformLabel("GROWW")).toBe("Groww");
    expect(platformLabel("groww")).toBe("Groww");
    expect(platformLabel("zerodha coin")).toBe("Zerodha Coin");
    expect(platformLabel("ET Money")).toBe("ET Money");
    expect(platformLabel("INDmoney")).toBe("INDmoney");
    expect(platformLabel("  Kuvera ")).toBe("Kuvera");
    expect(platformLabel("")).toBe("");
  });
});

describe("dates and countdown", () => {
  it("words the short date", () => {
    expect(shortDate("2026-12-02")).toBe("2 Dec");
  });

  it("counts down in days", () => {
    expect(countdownText("2026-12-02", "2026-11-06")).toBe("in 26 days");
    expect(countdownText("2026-11-07", "2026-11-06")).toBe("tomorrow");
    expect(countdownText("2026-11-06", "2026-11-06")).toBe("today");
    expect(countdownText("2026-11-05", "2026-11-06")).toBe("overdue");
    expect(countdownText("2027-01-05", "2026-12-31")).toBe("in 5 days");
  });
});

describe("summary", () => {
  const list = [
    sip({ id: 1, amount: 10000, next_date: "2026-12-02", invested_via_sip: 30000, instalments_added: 3 }),
    sip({ id: 2, amount: 10000, next_date: "2026-11-20", invested_via_sip: 20000, instalments_added: 2 }),
    sip({ id: 3, status: "paused", next_date: null, amount: 500, invested_via_sip: 1000, instalments_added: 2 }),
    sip({ id: 4, status: "stopped", next_date: null, amount: 700, invested_via_sip: 700, instalments_added: 1 }),
  ];

  it("sums the monthly amount of active SIPs and the invested and instalments of all", () => {
    expect(sipSummary(list)).toEqual({
      activeCount: 2,
      monthly: 20000,
      invested: 51700,
      instalments: 8,
      nextDate: "2026-11-20",
    });
  });

  it("ignores a skipped next instalment when picking the next date", () => {
    const s = sipSummary([
      { ...list[1], skipped_dates: ["2026-11-20"] },
      list[0],
    ]);
    expect(s.nextDate).toBe("2026-12-02");
  });

  it("handles no active SIPs", () => {
    expect(sipSummary([list[2], list[3]])).toMatchObject({ activeCount: 0, monthly: 0, nextDate: null });
    expect(sipSummary([])).toMatchObject({ activeCount: 0, invested: 0, instalments: 0 });
  });

  it("words the summary line", () => {
    expect(summaryLine(sipSummary([list[0], list[2]]))).toBe("1 active · next 2 Dec 2026");
    expect(summaryLine(sipSummary(list))).toBe("2 active · next 20 Nov 2026");
    expect(summaryLine(sipSummary([list[2]]))).toBe("No active SIPs");
    expect(summaryLine({ ...sipSummary(list), nextDate: null })).toBe("2 active");
  });
});

describe("transactions", () => {
  it("labels SIP instalments, purchases and redemptions", () => {
    expect(transactionLabel({ kind: "purchase", sip: true })).toBe("SIP");
    expect(transactionLabel({ kind: "purchase", sip: false })).toBe("Purchase");
    expect(transactionLabel({ kind: "redemption", sip: false })).toBe("Redemption");
  });

  it("words the Show more button", () => {
    expect(showMoreLabel(36, 10)).toBe("Show 10 more · 26 left");
    expect(showMoreLabel(16, 10)).toBe("Show 6 more");
    expect(showMoreLabel(20, 10)).toBe("Show 10 more");
    expect(showMoreLabel(10, 10)).toBeNull();
    expect(showMoreLabel(0, 0)).toBeNull();
  });
});

describe("actions", () => {
  it("offers the right actions per status", () => {
    expect(availableActions(sip())).toEqual(["edit", "skip", "pause", "stop"]);
    expect(availableActions(sip({ skipped_dates: ["2026-12-05"] }))).toEqual([
      "edit",
      "undo",
      "pause",
      "stop",
    ]);
    expect(availableActions(sip({ status: "paused", next_date: null }))).toEqual([
      "edit",
      "resume",
      "stop",
    ]);
    expect(availableActions(sip({ status: "stopped", next_date: null }))).toEqual(["delete"]);
    expect(availableActions(sip({ next_date: null }))).toEqual(["edit", "pause", "stop"]);
  });

  it("builds the API paths", () => {
    expect(actionPath(sip(), "pause")).toBe("/sips/1/pause");
    expect(actionPath(sip(), "skip")).toBe("/sips/1/skip");
    expect(actionPath(sip(), "undo")).toBe("/sips/1/skip/2026-12-05");
  });
});

describe("isSoldHolding", () => {
  it("is true for a closed or sold holding only", () => {
    expect(isSoldHolding({ closed_on: "2026-03-01", status: "sold" })).toBe(true);
    expect(isSoldHolding({ closed_on: "2026-03-01" })).toBe(true);
    expect(isSoldHolding({ closed_on: null, status: "active" })).toBe(false);
  });
});

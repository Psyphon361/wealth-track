import { describe, expect, it } from "vitest";
import {
  ALL_BONDS,
  axisLabels,
  axisLayout,
  bucketFy,
  bucketStatus,
  cardLeftBeside,
  combinedNext,
  couponProgress,
  daysText,
  daysUntil,
  dateTile,
  payoutPaging,
  payoutStatusText,
  showMoreCount,
  fyMarkers,
  fyPlacements,
  fyShares,
  fyPayoutRows,
  fyShort,
  groupItems,
  hoverSummary,
  maxColumn,
  mergeFy,
  monthBuckets,
  nextBucketIndex,
  nextSubline,
  optionDetail,
  optionLabel,
  redemptionLabel,
  selectBonds,
  approxAmount,
  hasPlannedSale,
  nonCouponLine,
  payoutsNote,
  plannedSaleLabel,
  plannedSaleNote,
} from "./bond-schedule";
import type { BondPayment, BondScheduleBond } from "./types";

const pay = (over: Partial<BondPayment> = {}): BondPayment => ({
  date: "2027-04-18",
  kind: "coupon",
  gross: 400,
  tds: 40,
  net: 360,
  fy: "2027-28",
  paid: false,
  ...over,
});

const bond = (over: Partial<BondScheduleBond> = {}): BondScheduleBond => ({
  id: 1,
  name: "Ugro 2027",
  issuer: "Ugro",
  bond_type: "corporate",
  coupon_rate: 9.5,
  frequency: "monthly",
  face_value: 1000,
  quantity: 50,
  purchase_date: "2026-11-05",
  maturity_date: "2027-03-20",
  planned_sale: false,
  bond_maturity_date: "2027-03-20",
  tds_rate: 10,
  estimated: true,
  payments: [],
  next_payment: null,
  by_fy: [],
  ...over,
});

describe("dates and labels", () => {
  it("counts days without a timezone shift", () => {
    expect(daysUntil("2026-03-01", "2026-02-01")).toBe(28);
    expect(daysUntil("2026-11-18", "2026-11-04")).toBe(14);
  });
  it("words the countdown", () => {
    expect(daysText(0)).toBe("today");
    expect(daysText(1)).toBe("tomorrow");
    expect(daysText(14)).toBe("in 14 days");
  });
  it("shortens a financial year", () => {
    expect(fyShort("2027-28")).toBe("FY 27–28");
  });
  it("labels select options", () => {
    expect(optionLabel(bond({ quantity: 1200 }))).toBe(
      "Ugro 2027 · 1,200 units · bought 5 Nov 2026",
    );
    expect(optionLabel(bond({ quantity: 1 }))).toContain("1 unit ·");
    expect(optionDetail(bond({ quantity: 1200 }))).toBe("1,200 units · bought 5 Nov 2026");
  });
  it("selects one bond or all, falling back to all", () => {
    const bonds = [bond({ id: 1 }), bond({ id: 2 })];
    expect(selectBonds(bonds, ALL_BONDS)).toHaveLength(2);
    expect(selectBonds(bonds, "2").map((b) => b.id)).toEqual([2]);
    expect(selectBonds(bonds, "9")).toHaveLength(2);
  });
  it("words the redemption label", () => {
    expect(redemptionLabel(100000)).toBe("₹1,00,000 back");
  });
});

describe("progress and next payout", () => {
  it("sums paid coupons against all coupons, ignoring redemption", () => {
    const b = bond({
      payments: [
        pay({ gross: 100, paid: true }),
        pay({ gross: 100, paid: true }),
        pay({ gross: 200 }),
        pay({ kind: "redemption", gross: 5000, tds: 0, net: 5000 }),
      ],
    });
    const p = couponProgress([b]);
    expect(p).toEqual({ received: 200, total: 400, pct: 50 });
    expect(couponProgress([bond()]).pct).toBe(0);
  });
  it("combines bonds paying on the soonest date", () => {
    const a = bond({ id: 1, name: "A", next_payment: pay({ date: "2026-11-18" }) });
    const b = bond({ id: 2, name: "B", next_payment: pay({ date: "2026-11-18", gross: 100, tds: 0, net: 100 }) });
    const c = bond({ id: 3, name: "C", next_payment: pay({ date: "2026-12-18" }) });
    const n = combinedNext([a, b, c], "2026-11-04");
    expect(n).toMatchObject({ date: "2026-11-18", days: 14, coupon: 500, tds: 40, net: 460 });
    expect(n?.names).toEqual(["A", "B"]);
    expect(combinedNext([bond()], "2026-11-04")).toBeNull();
  });
  it("words the subline", () => {
    const fmt = (v: number) => `₹${v}`;
    const coupon = combinedNext([bond({ next_payment: pay({ date: "2026-11-18" }) })], "2026-11-04")!;
    expect(nextSubline(coupon, fmt)).toBe("₹400 coupon − ₹40 TDS");
    const red = combinedNext(
      [bond({ next_payment: pay({ kind: "redemption", gross: 5000, tds: 0, net: 5000 }) })],
      "2026-11-04",
    )!;
    expect(nextSubline(red, fmt)).toBe("₹5000 repaid at maturity");
  });
});

describe("monthBuckets", () => {
  const b = bond({
    payments: [
      pay({ date: "2026-12-20", paid: true }),
      pay({ date: "2027-03-20", gross: 100, tds: 10, net: 90 }),
      pay({ date: "2027-03-20", kind: "redemption", gross: 5000, tds: 0, net: 5000 }),
    ],
  });
  it("spans purchase month to maturity month", () => {
    const m = monthBuckets([b]);
    expect(m.map((x) => x.key)).toEqual(["2026-11", "2026-12", "2027-01", "2027-02", "2027-03"]);
    expect(m[4].index).toBe(4);
  });
  it("keeps redemption out of the bar totals", () => {
    const m = monthBuckets([b]);
    expect(m[4]).toMatchObject({ gross: 100, tds: 10, net: 90, redemption: 5000, paid: false });
    expect(m[1]).toMatchObject({ net: 360, paid: true });
    expect(m[2].items).toEqual([]);
    expect(m[2].paid).toBe(false);
  });
  it("aggregates several bonds in one month", () => {
    const m = monthBuckets([
      bond({ id: 1, payments: [pay({ date: "2026-12-20" })] }),
      bond({ id: 2, name: "B", payments: [pay({ date: "2026-12-05" })] }),
    ]);
    expect(m[1].net).toBe(720);
    expect(m[1].items.map((i) => i.name)).toEqual(["B", "Ugro 2027"]);
  });
  it("maps a month to its financial year", () => {
    const m = monthBuckets([bond({ purchase_date: "2027-03-01", maturity_date: "2027-04-01" })]);
    expect(bucketFy(m[0])).toBe("2026-27");
    expect(bucketFy(m[1])).toBe("2027-28");
  });
  it("finds the next month and the tallest column", () => {
    const m = monthBuckets([b]);
    expect(nextBucketIndex(m, "2027-03-20")).toBe(4);
    expect(nextBucketIndex(m, null)).toBeNull();
    expect(maxColumn(m)).toBe(400);
    expect(maxColumn([])).toBe(1);
    expect(monthBuckets([])).toEqual([]);
  });
});

describe("axis", () => {
  const months = (n: number) =>
    monthBuckets([bond({ purchase_date: "2026-01-10", maturity_date: new Date(Date.UTC(2026, n - 1, 10)).toISOString().slice(0, 10) })]);

  it("fits up to 14 months and scrolls beyond", () => {
    expect(axisLayout(14).scroll).toBe(false);
    expect(axisLayout(15).scroll).toBe(true);
  });
  it("never lets labels overlap", () => {
    for (const n of [1, 3, 6, 12, 14, 15, 36, 120]) {
      const { slot, step } = axisLayout(n);
      expect(step * slot).toBeGreaterThanOrEqual(30);
    }
  });
  it("labels every step-th month and shows the year when it changes", () => {
    const labels = axisLabels(months(15), 2);
    expect(labels.map((l) => l.index)).toEqual([0, 2, 4, 6, 8, 10, 12, 14]);
    expect(labels[0]).toEqual({ index: 0, month: "Jan", year: 2026 });
    expect(labels[1].year).toBeNull();
    const longer = axisLabels(
      monthBuckets([bond({ purchase_date: "2026-11-01", maturity_date: "2027-03-01" })]),
      2,
    );
    expect(longer.map((l) => l.year)).toEqual([2026, 2027, null]);
  });
  it("marks each April after the first column", () => {
    const m = monthBuckets([bond({ purchase_date: "2027-03-01", maturity_date: "2028-05-01" })]);
    expect(fyMarkers(m)).toEqual([
      { index: 1, label: "FY 27–28" },
      { index: 13, label: "FY 28–29" },
    ]);
    const first = monthBuckets([bond({ purchase_date: "2027-04-01", maturity_date: "2027-06-01" })]);
    expect(fyMarkers(first)).toEqual([]);
  });
  it("places FY labels so none is clipped", () => {
    const mk = (index: number) => ({ index, label: `FY ${index}` });
    expect(fyPlacements([mk(1), mk(13)], 24, 12.5).map((p) => p.align)).toEqual(["left", "left"]);
    // 2 columns of 12.5px left after the line: flip to the left side
    expect(fyPlacements([mk(1), mk(13)], 15, 12.5).map((p) => p.align)).toEqual(["left", "right"]);
    // no room on either side: skipped
    expect(fyPlacements([mk(1), mk(3)], 4, 12.5)).toEqual([]);
    expect(fyPlacements([], 10, 20)).toEqual([]);
  });
});

describe("per-year rows", () => {
  it("sums across bonds, oldest first, and shares the net", () => {
    const rows = mergeFy([
      bond({
        by_fy: [
          { fy: "2027-28", coupons: 1, gross: 100, tds: 10, net: 90 },
          { fy: "2026-27", coupons: 2, gross: 200, tds: 20, net: 180 },
        ],
      }),
      bond({ id: 2, by_fy: [{ fy: "2026-27", coupons: 4, gross: 400, tds: 0, net: 400 }] }),
    ]);
    expect(rows).toEqual([
      { fy: "2026-27", coupons: 6, gross: 600, tds: 20, net: 580 },
      { fy: "2027-28", coupons: 1, gross: 100, tds: 10, net: 90 },
    ]);
    const shares = fyShares(rows);
    expect(shares[0] + shares[1]).toBeCloseTo(100);
    expect(fyShares([])).toEqual([]);
  });
});

const item = (over: Partial<BondPayment> & { id?: number; name?: string } = {}) => {
  const { id = 1, name = "Ugro 2027", ...p } = over;
  return bond({ id, name, payments: [pay(p)] });
};
const apr = (bonds: BondScheduleBond[]) => monthBuckets(bonds).find((b) => b.key === "2027-04")!;

describe("hover card", () => {
  it("words the status", () => {
    expect(bucketStatus([{ paid: true }, { paid: true }])).toBe("Paid");
    expect(bucketStatus([{ paid: false }, { paid: false }])).toBe("Upcoming");
    expect(bucketStatus([{ paid: true }, { paid: false }])).toBe("Part paid");
    expect(bucketStatus([])).toBe("Upcoming");
  });

  it("combines identical lines and adds x N only when more than one", () => {
    const m = apr([
      bond({
        payments: [
          pay({ date: "2027-04-10", net: 100 }),
          pay({ date: "2027-04-20", net: 150 }),
          pay({ date: "2027-04-25", net: 40 }),
        ],
      }),
      bond({ id: 2, name: "Other", payments: [pay({ net: 90 })] }),
    ]);
    expect(groupItems(m.items)).toEqual([
      { key: "coupon|Ugro 2027", label: "Ugro 2027 ×3", amount: 290 },
      { key: "coupon|Other", label: "Other", amount: 90 },
    ]);
  });

  it("keeps a repayment apart from the coupon of the same bond", () => {
    const m = apr([
      bond({
        purchase_date: "2027-04-01",
        maturity_date: "2027-04-18",
        payments: [pay({ net: 360 }), pay({ kind: "redemption", gross: 50000, tds: 0, net: 50000 })],
      }),
    ]);
    expect(groupItems(m.items)).toEqual([
      { key: "redemption|Ugro 2027", label: "Ugro 2027 · Repayment", amount: 50000 },
      { key: "coupon|Ugro 2027", label: "Ugro 2027", amount: 360 },
    ]);
  });

  it("shows the top three rows and counts the rest", () => {
    const bonds = [100, 400, 200, 300, 50].map((net, i) =>
      item({ id: i + 1, name: `B${i + 1}`, net }),
    );
    const m = apr(bonds);
    const s = hoverSummary(m, true);
    expect(s.rows.map((r) => r.label)).toEqual(["B2", "B4", "B3"]);
    expect(s.more).toBe(2);
    expect(s.title).toBe("Apr 2027");
    expect(s.status).toBe("Upcoming");
    expect(s.amount).toBe(1050);
    expect(s.amountLabel).toBe("net");
    expect(s.coupon).toBe(2000);
    expect(s.tds).toBe(200);
  });

  it("has no more count when the rows fit", () => {
    const m = apr([item()]);
    expect(hoverSummary(m, true).more).toBe(0);
  });

  it("omits the item list for a single bond but keeps its repayment line", () => {
    const m = apr([
      bond({
        purchase_date: "2027-04-01",
        maturity_date: "2027-04-18",
        payments: [pay({ net: 360 }), pay({ kind: "redemption", gross: 50000, tds: 0, net: 50000 })],
      }),
    ]);
    const s = hoverSummary(m, false);
    expect(s.rows).toEqual([{ key: "redemption|Ugro 2027", label: "Ugro 2027 · Repayment", amount: 50000 }]);
    const plain = apr([item()]);
    expect(hoverSummary(plain, false).rows).toEqual([]);
  });

  it("headlines the repayment when the month has no coupon", () => {
    const m = apr([
      item({ kind: "redemption", gross: 50000, tds: 0, net: 50000, paid: true }),
    ]);
    const s = hoverSummary(m, false);
    expect(s.amount).toBe(50000);
    expect(s.amountLabel).toBe("repaid");
    expect(s.coupon).toBeNull();
    expect(s.rows).toEqual([]);
    expect(s.status).toBe("Paid");
  });

  it("puts the card to the right of the bar when it fits", () => {
    expect(cardLeftBeside(100, 120, 200, 500, 8)).toBe(128);
    expect(cardLeftBeside(0, 20, 200, 228, 8)).toBe(28);
  });

  it("flips to the left of the bar near the right edge", () => {
    expect(cardLeftBeside(400, 420, 200, 500, 8)).toBe(192);
    expect(cardLeftBeside(300, 320, 200, 500, 8)).toBe(92);
  });

  it("stays inside the view when neither side fits", () => {
    expect(cardLeftBeside(100, 120, 200, 200, 8)).toBe(0);
    expect(cardLeftBeside(150, 170, 300, 200, 8)).toBe(0);
    expect(cardLeftBeside(100, 120, 200, 300, 8)).toBe(100);
  });
});

describe("fyPayoutRows", () => {
  const ugroA = bond({
    id: 1,
    name: "Ugro 2027",
    payments: [
      pay({ date: "2027-05-18", fy: "2027-28" }),
      pay({ date: "2027-04-18", fy: "2027-28", paid: true }),
      pay({ date: "2027-03-18", fy: "2026-27" }),
    ],
  });
  const ugroB = bond({
    id: 2,
    name: "Ugro 2027",
    payments: [pay({ date: "2027-04-18", fy: "2027-28", paid: false })],
  });
  const other = bond({
    id: 3,
    name: "Acme 2028",
    payments: [
      pay({ date: "2027-04-18", fy: "2027-28", gross: 100, tds: 0, net: 100 }),
      pay({ date: "2027-06-30", fy: "2027-28", kind: "redemption", gross: 50000, tds: 0, net: 50000 }),
    ],
  });

  it("keeps only the chosen financial year", () => {
    const rows = fyPayoutRows([ugroA], "2026-27");
    expect(rows).toHaveLength(1);
    expect(rows[0].date).toBe("2027-03-18");
    expect(fyPayoutRows([ugroA], "2030-31")).toEqual([]);
  });

  it("combines identical lines of the same bond name on the same date with summed amounts", () => {
    const rows = fyPayoutRows([ugroA, ugroB], "2027-28");
    const merged = rows.find((r) => r.date === "2027-04-18")!;
    expect(merged.count).toBe(2);
    expect(merged.gross).toBe(800);
    expect(merged.tds).toBe(80);
    expect(merged.net).toBe(720);
    expect(merged.paid).toBe(false);
    expect(rows).toHaveLength(2);
  });

  it("does not combine different bonds or different dates", () => {
    const rows = fyPayoutRows([ugroA, ugroB, other], "2027-28");
    const onApr18 = rows.filter((r) => r.date === "2027-04-18");
    expect(onApr18.map((r) => r.name)).toEqual(["Acme 2028", "Ugro 2027"]);
    expect(onApr18[0].count).toBe(1);
  });

  it("sorts by date and keeps a repayment as its own row", () => {
    const rows = fyPayoutRows([ugroA, other], "2027-28");
    expect(rows.map((r) => r.date)).toEqual(["2027-04-18", "2027-04-18", "2027-05-18", "2027-06-30"]);
    const repay = rows[rows.length - 1];
    expect(repay.kind).toBe("redemption");
    expect(repay.gross).toBe(50000);
    expect(rows.filter((r) => r.kind === "coupon")).toHaveLength(3);
  });

  it("coupon rows add up to the year totals and exclude repayments", () => {
    const rows = fyPayoutRows([other], "2027-28");
    const coupons = rows.filter((r) => r.kind === "coupon");
    expect(coupons.reduce((s, r) => s + r.gross, 0)).toBe(100);
  });

  it("works for a single bond", () => {
    const rows = fyPayoutRows([other], "2027-28");
    expect(rows.map((r) => r.kind)).toEqual(["coupon", "redemption"]);
    expect(rows.every((r) => r.name === "Acme 2028")).toBe(true);
  });

  it("puts a coupon before a repayment on the same date", () => {
    const b = bond({
      payments: [
        pay({ date: "2027-06-30", kind: "redemption", gross: 1000, tds: 0, net: 1000 }),
        pay({ date: "2027-06-30" }),
      ],
    });
    expect(fyPayoutRows([b], "2027-28").map((r) => r.kind)).toEqual(["coupon", "redemption"]);
  });
});

describe("planned sale", () => {
  const sale = (over: Partial<BondPayment> = {}) =>
    pay({ kind: "sale", gross: 50000, tds: 0, net: 50000, estimated_value: true, ...over });
  const saleBond = (over: Partial<BondScheduleBond> = {}) =>
    bond({
      planned_sale: true,
      purchase_date: "2027-04-01",
      maturity_date: "2027-04-18",
      bond_maturity_date: "2027-12-07",
      payments: [pay({ net: 360 }), sale()],
      ...over,
    });

  it("words the amounts and labels", () => {
    expect(approxAmount("₹50,000")).toBe("≈ ₹50,000");
    expect(plannedSaleLabel(50000)).toBe("≈ ₹50,000 planned sale");
    expect(nonCouponLine("sale")).toBe("◇ Planned sale · estimated");
    expect(nonCouponLine("redemption")).toBe("◆ Repayment of principal");
  });

  it("words the single-bond note, leaving out an unknown maturity", () => {
    const b = saleBond({ maturity_date: "2027-01-07", bond_maturity_date: "2027-12-07" });
    expect(plannedSaleNote(b)).toBe("You plan to sell on 7 Jan 2027; the bond matures 7 Dec 2027.");
    expect(plannedSaleNote({ ...b, bond_maturity_date: null })).toBe("You plan to sell on 7 Jan 2027.");
    expect(plannedSaleNote(bond())).toBeNull();
  });

  it("detects a planned sale among the shown bonds", () => {
    expect(hasPlannedSale([bond(), saleBond()])).toBe(true);
    expect(hasPlannedSale([bond({ payments: [pay()] })])).toBe(false);
  });

  it("words the year note by what the year holds", () => {
    expect(payoutsNote([{ kind: "coupon" }])).toBeNull();
    expect(payoutsNote([{ kind: "coupon" }, { kind: "redemption" }])).toBe(
      "Repayments aren't in the year totals.",
    );
    expect(payoutsNote([{ kind: "coupon" }, { kind: "sale" }])).toBe(
      "Repayments and planned sales aren't in the year totals.",
    );
  });

  it("keeps the sale out of the bars and in its own marker amount", () => {
    const m = apr([saleBond()]);
    expect(m).toMatchObject({ net: 360, sale: 50000, redemption: 0 });
    expect(maxColumn([m])).toBe(400);
  });

  it("keeps a sale apart from the coupon and from a repayment", () => {
    const m = apr([
      saleBond(),
      bond({ id: 2, name: "Other", payments: [pay({ kind: "redemption", gross: 1000, tds: 0, net: 1000 })] }),
    ]);
    expect(groupItems(m.items)).toEqual([
      { key: "sale|Ugro 2027", label: "Ugro 2027 · Planned sale", amount: 50000, approx: true },
      { key: "redemption|Other", label: "Other · Repayment", amount: 1000 },
      { key: "coupon|Ugro 2027", label: "Ugro 2027", amount: 360 },
    ]);
  });

  it("headlines a sale-only month as an estimate", () => {
    const m = apr([saleBond({ payments: [sale()] })]);
    const s = hoverSummary(m, false);
    expect(s).toMatchObject({ amount: 50000, amountLabel: "planned sale", approx: true, coupon: null });
    expect(s.rows).toEqual([]);
  });

  it("lists the sale line for one bond that also has a coupon that month", () => {
    const s = hoverSummary(apr([saleBond()]), false);
    expect(s).toMatchObject({ amountLabel: "net", approx: false });
    expect(s.rows).toEqual([
      { key: "sale|Ugro 2027", label: "Ugro 2027 · Planned sale", amount: 50000, approx: true },
    ]);
  });

  it("does not mark a repayment-only month as an estimate", () => {
    const m = apr([item({ kind: "redemption", gross: 50000, tds: 0, net: 50000 })]);
    expect(hoverSummary(m, false)).toMatchObject({ amountLabel: "repaid", approx: false });
  });

  it("combines the soonest sale in the next-payout subline", () => {
    const fmt = (v: number) => `₹${v}`;
    const n = combinedNext([saleBond({ next_payment: sale({ date: "2027-04-18" }) })], "2027-04-01")!;
    expect(n).toMatchObject({ sale: 50000, coupon: 0, redemption: 0, net: 50000 });
    expect(nextSubline(n, fmt)).toBe("≈ ₹50000 planned sale");
  });

  it("lists a sale as its own payout row after the coupon of the same date", () => {
    const b = saleBond({ payments: [sale(), pay()] });
    expect(fyPayoutRows([b], "2027-28").map((r) => r.kind)).toEqual(["coupon", "sale"]);
  });
});

describe("payout paging", () => {
  it("shows the first ten with a count of the rest", () => {
    const p = payoutPaging(36, 10);
    expect(p.visible).toBe(10);
    expect(p.left).toBe(26);
    expect(p.moreLabel).toBe("Show 10 more · 26 left");
    expect(p.canShowLess).toBe(false);
  });

  it("drops the 'left' part when the rest fits in one step", () => {
    expect(payoutPaging(16, 10).moreLabel).toBe("Show 6 more");
    expect(payoutPaging(20, 10).moreLabel).toBe("Show 10 more");
    expect(payoutPaging(21, 10).moreLabel).toBe("Show 10 more · 11 left");
  });

  it("offers Show less only once everything is shown and there was more than one page", () => {
    const all = payoutPaging(16, 16);
    expect(all.visible).toBe(16);
    expect(all.moreLabel).toBeNull();
    expect(all.canShowLess).toBe(true);
    const short = payoutPaging(7, 10);
    expect(short.visible).toBe(7);
    expect(short.moreLabel).toBeNull();
    expect(short.canShowLess).toBe(false);
    expect(payoutPaging(10, 10).canShowLess).toBe(false);
    expect(payoutPaging(0, 10)).toEqual({ visible: 0, left: 0, moreLabel: null, canShowLess: false });
  });

  it("never shows fewer than one page", () => {
    expect(payoutPaging(36, 0).visible).toBe(10);
  });

  it("steps by a page and stops at the total", () => {
    expect(showMoreCount(36, 10)).toBe(20);
    expect(showMoreCount(36, 30)).toBe(36);
    expect(showMoreCount(16, 10)).toBe(16);
    expect(payoutPaging(36, showMoreCount(36, 30)).left).toBe(0);
  });
});

describe("payout row text", () => {
  it("splits an ISO date into day, month and two-digit year", () => {
    expect(dateTile("2026-04-18")).toEqual({ day: 18, month: "Apr", year: "26" });
    expect(dateTile("2031-01-05")).toEqual({ day: 5, month: "Jan", year: "31" });
    expect(dateTile("2009-12-31")).toEqual({ day: 31, month: "Dec", year: "09" });
  });

  it("writes the status line with the holdings count only above one", () => {
    expect(payoutStatusText(true, 1)).toBe("Paid");
    expect(payoutStatusText(false, 1)).toBe("Upcoming");
    expect(payoutStatusText(true, 2)).toBe("Paid · 2 holdings");
    expect(payoutStatusText(false, 3)).toBe("Upcoming · 3 holdings");
  });
});

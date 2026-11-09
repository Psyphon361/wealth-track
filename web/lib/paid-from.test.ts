import { describe, expect, it } from "vitest";
import {
  PAID_FROM_EDIT_DELETED_ERROR,
  PAID_FROM_EDIT_GONE_NOTE,
  PAID_FROM_EDIT_NOT_IN_SYNC_NOTE,
  PAID_FROM_EDIT_TOO_MUCH_ERROR,
  PAID_FROM_EDIT_ZERO_ERROR,
  accountLabel,
  inr,
  paidFromAmount,
  paidFromBody,
  paidFromEditLine,
  paidFromEffect,
  paidFromError,
  paidFromReadOnly,
  rdInstalmentsPaid,
  recordPaidFrom,
  reinvestNote,
} from "./paid-from";

const hdfc = { id: 4, name: "HDFC Savings", balance: 225000 };
const TODAY = "2026-11-07";

describe("paidFromEditLine", () => {
  const base = {
    cash_holding_id: 4,
    cash_name: "HDFC Savings",
    amount: 50000,
    date: "2026-11-02",
    adjustable: true,
    reason: null,
  } as const;

  it("shows nothing while the cost is unchanged or the balance is unknown", () => {
    expect(paidFromEditLine(base, 225000, 50000)).toBeNull();
    expect(paidFromEditLine(base, null, 60000)).toBeNull();
  });

  it("shows the new balance for an increase and a decrease", () => {
    expect(paidFromEditLine(base, 225000, 60000)).toEqual({
      text: "HDFC Savings: ₹2,25,000 → ₹2,15,000",
      tone: "effect",
    });
    expect(paidFromEditLine(base, 225000, 40000)).toEqual({
      text: "HDFC Savings: ₹2,25,000 → ₹2,35,000",
      tone: "effect",
    });
  });

  it("flags an increase over the balance with the shortfall", () => {
    expect(paidFromEditLine(base, 5000, 60000)).toEqual({
      text: "Not enough in HDFC Savings: short by ₹5,000",
      tone: "error",
    });
  });

  it("flags a blank or zero cost", () => {
    expect(paidFromEditLine(base, 225000, null)).toEqual({
      text: PAID_FROM_EDIT_ZERO_ERROR,
      tone: "error",
    });
  });

  it("explains each reason when not adjustable", () => {
    const off = { ...base, adjustable: false };
    expect(paidFromEditLine({ ...off, reason: "out_of_sync" }, 1, 2)?.text).toBe(
      PAID_FROM_EDIT_NOT_IN_SYNC_NOTE.replace("{account}", "HDFC Savings"),
    );
    expect(paidFromEditLine({ ...off, reason: "account_deleted" }, 1, 2)?.text).toBe(
      PAID_FROM_EDIT_DELETED_ERROR.replace("{account}", "HDFC Savings"),
    );
    expect(
      paidFromEditLine(
        { ...off, cash_holding_id: null, cash_name: null, reason: "account_gone" },
        null,
        2,
      )?.text,
    ).toBe(PAID_FROM_EDIT_GONE_NOTE);
    expect(paidFromEditLine({ ...off, reason: "type" }, 1, 2)).toBeNull();
  });
});

describe("inr", () => {
  it("groups the Indian way and drops zero paise", () => {
    expect(inr(225000)).toBe("₹2,25,000");
    expect(inr(1071.5)).toBe("₹1,071.50");
  });
});

describe("rdInstalmentsPaid", () => {
  it("counts instalments on or before today, before maturity", () => {
    expect(rdInstalmentsPaid("2026-01-05", 1, 0, 0, TODAY)).toBe(11);
    expect(rdInstalmentsPaid("2026-11-07", 1, 0, 0, TODAY)).toBe(1);
    expect(rdInstalmentsPaid("2026-11-08", 1, 0, 0, TODAY)).toBe(0);
  });
  it("stops at maturity", () => {
    expect(rdInstalmentsPaid("2025-01-01", 0, 6, 0, TODAY)).toBe(6);
  });
  it("is 0 for an invalid start", () => {
    expect(rdInstalmentsPaid("", 1, 0, 0, TODAY)).toBe(0);
  });
});

describe("paidFromAmount", () => {
  it("reads the invested amount for each type", () => {
    expect(paidFromAmount("fd", { principal: "50000" })).toBe(50000);
    expect(paidFromAmount("stock", { quantity: "10", avg_buy_price: "250.5" })).toBe(2505);
    expect(paidFromAmount("bond", { invested_amount: "98000" })).toBe(98000);
    expect(paidFromAmount("mf", { invested_amount: "1000" })).toBe(1000);
    expect(paidFromAmount("nps", { contributed: "5000" })).toBe(5000);
    expect(paidFromAmount("gold", { invested_amount: "70000" })).toBe(70000);
    expect(paidFromAmount("cash", { balance: "300" })).toBe(300);
    expect(paidFromAmount("other", { invested_amount: "9000" })).toBe(9000);
  });
  it("uses contributed for pf, else the balance", () => {
    expect(paidFromAmount("pf", { contributed: "100", balance: "500" })).toBe(100);
    expect(paidFromAmount("pf", { contributed: "", balance: "500" })).toBe(500);
  });
  it("counts RD instalments paid so far", () => {
    expect(
      paidFromAmount(
        "rd",
        {
          monthly_instalment: "5000",
          start_date: "2026-01-05",
          tenure_years: "1",
          tenure_months: "0",
          tenure_days: "0",
        },
        TODAY,
      ),
    ).toBe(55000);
  });
  it("is null while blank or not positive", () => {
    expect(paidFromAmount("fd", { principal: "" })).toBeNull();
    expect(paidFromAmount("stock", { quantity: "10", avg_buy_price: "" })).toBeNull();
    expect(paidFromAmount("other", { invested_amount: "0" })).toBeNull();
    expect(paidFromAmount("other", {})).toBeNull();
  });
});

describe("paidFromEffect and labels", () => {
  it("shows the balance before and after", () => {
    expect(paidFromEffect(hdfc, 50000)).toBe("HDFC Savings: ₹2,25,000 → ₹1,75,000");
  });
  it("labels an option", () => {
    expect(accountLabel(hdfc)).toBe("HDFC Savings · ₹2,25,000");
  });
});

describe("paidFromError", () => {
  const accounts = [hdfc];
  it("is fine with no account", () => {
    expect(paidFromError("fd", null, accounts, 1e9)).toBeNull();
  });
  it("flags more than the balance, with the API wording", () => {
    expect(paidFromError("fd", 4, accounts, 225000.01)).toBe(
      "More than this account's balance",
    );
    expect(paidFromError("fd", 4, accounts, 225000)).toBeNull();
  });
  it("needs an amount for Other", () => {
    expect(paidFromError("other", 4, accounts, null)).toBe(
      "Enter the amount invested to pay it from an account",
    );
    expect(paidFromError("fd", 4, accounts, null)).toBeNull();
  });
  it("flags an account that isn't one of the user's", () => {
    expect(paidFromError("fd", 99, accounts, 10)).toBe("Choose one of your accounts");
  });
  it("waits while accounts load", () => {
    expect(paidFromError("fd", 4, null, 10)).toBeNull();
  });
});

describe("paidFromBody", () => {
  it("sends nothing for outside money", () => {
    expect(paidFromBody(null)).toEqual({});
  });
  it("sends the account and the exit it came from", () => {
    expect(paidFromBody(4)).toEqual({ paid_from: { cash_id: 4 } });
    expect(paidFromBody(4, 9)).toEqual({ paid_from: { cash_id: 4, from_exit_id: 9 } });
  });
});

describe("edit messages shared with the API", () => {
  it("keeps the wording of api/app/schemas/fundings.py", () => {
    expect(PAID_FROM_EDIT_TOO_MUCH_ERROR).toBe("Not enough in {account}: short by {shortfall}");
    expect(PAID_FROM_EDIT_DELETED_ERROR).toBe("Restore {account} first");
    expect(PAID_FROM_EDIT_ZERO_ERROR).toBe(
      "The cost must stay above zero while it is paid from an account",
    );
    expect(PAID_FROM_EDIT_NOT_IN_SYNC_NOTE).toBe(
      "The cost no longer matches the amount paid from {account}, so the account was not changed.",
    );
    expect(PAID_FROM_EDIT_GONE_NOTE).toBe(
      "The account it was paid from no longer exists, so no money moved.",
    );
  });
});

describe("record and notes", () => {
  it("reads the read-only line", () => {
    const p = recordPaidFrom({
      paid_from: { cash_holding_id: 4, cash_name: "HDFC Savings", amount: 50000, date: "2026-11-01" },
    });
    expect(p && paidFromReadOnly(p)).toBe("Paid from HDFC Savings · ₹50,000");
    expect(recordPaidFrom({ paid_from: null })).toBeNull();
    expect(recordPaidFrom({})).toBeNull();
  });
  it("writes the reinvest note", () => {
    expect(
      reinvestNote({
        type: "fd",
        amount: 107186,
        date: "2026-11-01",
        cash_id: 4,
        cash_name: "HDFC Savings",
      }),
    ).toBe("Reinvesting ₹1,07,186 from HDFC Savings.");
  });
});

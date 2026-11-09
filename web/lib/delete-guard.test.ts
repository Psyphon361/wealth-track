import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  DELETE_SETTLED_DESCRIPTION,
  DELETE_SETTLED_MESSAGE,
  DELETE_SOLD_DESCRIPTION,
  DELETE_SOLD_MESSAGE,
  deleteBlockedReason,
  isDeleteBlocked,
} from "./delete-guard";

const none = { exit: null };
const partly = { exit: { kind: "sale" as const } };
const sold = { exit: { kind: "sale" as const }, status: "sold" };
const settled = { exit: { kind: "maturity" as const } };

describe("delete guard", () => {
  it("allows a holding with no exit", () => {
    expect(isDeleteBlocked(none)).toBe(false);
    expect(isDeleteBlocked({})).toBe(false);
    expect(deleteBlockedReason(none)).toBeNull();
  });

  it("blocks a partly sold holding with the sale wording", () => {
    expect(isDeleteBlocked(partly)).toBe(true);
    expect(deleteBlockedReason(partly)).toEqual({
      message: DELETE_SOLD_MESSAGE,
      description: DELETE_SOLD_DESCRIPTION,
    });
  });

  it("blocks a fully sold holding with the sale wording", () => {
    expect(isDeleteBlocked(sold)).toBe(true);
    expect(deleteBlockedReason(sold)?.message).toBe("Undo the sale first");
  });

  it("blocks a settled or matured holding with the settlement wording", () => {
    expect(isDeleteBlocked(settled)).toBe(true);
    expect(deleteBlockedReason(settled)).toEqual({
      message: DELETE_SETTLED_MESSAGE,
      description: DELETE_SETTLED_DESCRIPTION,
    });
  });

  it("uses the sale wording when a sale is the exit shown, even with a settlement too", () => {
    expect(deleteBlockedReason({ exit: { kind: "sale" } })?.message).toBe(DELETE_SOLD_MESSAGE);
  });

  it("allows delete again once every exit is undone", () => {
    const afterUndo = { ...sold, exit: null };
    expect(isDeleteBlocked(afterUndo)).toBe(false);
    expect(deleteBlockedReason(afterUndo)).toBeNull();
  });

  it("matches the API wording", () => {
    const api = readFileSync(
      new URL("../../api/app/schemas/exits.py", import.meta.url),
      "utf8",
    );
    for (const text of [
      DELETE_SOLD_MESSAGE,
      DELETE_SOLD_DESCRIPTION,
      DELETE_SETTLED_MESSAGE,
      DELETE_SETTLED_DESCRIPTION,
    ]) {
      expect(api).toContain(`"${text}"`);
    }
  });
});

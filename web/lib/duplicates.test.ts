import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import {
  confirmDuplicatePath,
  duplicateHref,
  readDuplicates,
} from "./duplicates";

describe("readDuplicates", () => {
  it("reads the matches of a 409", () => {
    const err = new ApiError(409, "m", "d", undefined, [
      { id: 1, name: "SBI · FD" },
      { id: 2, name: "HDFC · FD" },
    ]);
    expect(readDuplicates(err)).toEqual([
      { id: 1, name: "SBI · FD" },
      { id: 2, name: "HDFC · FD" },
    ]);
  });

  it("skips malformed entries", () => {
    const err = new ApiError(409, "m", "d", undefined, [
      { id: "1", name: "x" },
      null,
      { id: 3, name: "Ok" },
    ]);
    expect(readDuplicates(err)).toEqual([{ id: 3, name: "Ok" }]);
  });

  it("returns null for other statuses, empty lists and non-API errors", () => {
    expect(
      readDuplicates(new ApiError(422, "m", "d", undefined, [{ id: 1, name: "a" }])),
    ).toBeNull();
    expect(readDuplicates(new ApiError(409, "m", "d", undefined, []))).toBeNull();
    expect(readDuplicates(new ApiError(409, "m", "d"))).toBeNull();
    expect(readDuplicates(new Error("x"))).toBeNull();
  });
});

describe("confirmDuplicatePath", () => {
  it("adds the query flag", () => {
    expect(confirmDuplicatePath("/assets/fd")).toBe(
      "/assets/fd?confirm_duplicate=true",
    );
    expect(confirmDuplicatePath("/sips?x=1")).toBe(
      "/sips?x=1&confirm_duplicate=true",
    );
  });
});

describe("duplicateHref", () => {
  it("links to the details page", () => {
    expect(duplicateHref("fd", 7)).toBe("/portfolio/fd/7");
  });
});

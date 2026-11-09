/** Same wording as the API's delete refusals (api/app/schemas/exits.py). */
export const DELETE_SOLD_MESSAGE = "Undo the sale first";
export const DELETE_SOLD_DESCRIPTION = "Delete this holding after you undo its sale.";
export const DELETE_SETTLED_MESSAGE = "Undo the settlement first";
export const DELETE_SETTLED_DESCRIPTION = "Delete this holding after you undo its settlement.";

/** The part of a valued holding the delete rule looks at. */
export interface DeleteGuardRow {
  exit?: { kind: "maturity" | "sale" } | null;
}

/** A holding with a sale or settlement can't be deleted until the exit is undone. */
export function isDeleteBlocked(item: DeleteGuardRow): boolean {
  return item.exit != null;
}

/** Why Delete is disabled, or null when it is allowed. A sale wins over a settlement, as in the API. */
export function deleteBlockedReason(
  item: DeleteGuardRow,
): { message: string; description: string } | null {
  if (!item.exit) return null;
  if (item.exit.kind === "sale") {
    return { message: DELETE_SOLD_MESSAGE, description: DELETE_SOLD_DESCRIPTION };
  }
  return { message: DELETE_SETTLED_MESSAGE, description: DELETE_SETTLED_DESCRIPTION };
}

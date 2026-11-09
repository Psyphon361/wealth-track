"""The optional `paid_from` of POST /api/assets/{type} ("Paid from" a Cash & Savings account).

The validation messages are shared verbatim with the web forms. "Choose one of your accounts" is
reused from schemas/exits.py.
"""

from pydantic import BaseModel

PAID_FROM_TOO_MUCH_ERROR = "More than this account's balance"
PAID_FROM_OTHER_AMOUNT_ERROR = "Enter the amount invested to pay it from an account"

# Editing the cost of a holding that was paid from an account (PUT). `{account}` and `{shortfall}`
# are filled in by the API; the web keeps the same wording in web/lib/paid-from.ts.
PAID_FROM_EDIT_TOO_MUCH_ERROR = "Not enough in {account}: short by {shortfall}"
PAID_FROM_EDIT_DELETED_ERROR = "Restore {account} first"
PAID_FROM_EDIT_ZERO_ERROR = "The cost must stay above zero while it is paid from an account"
PAID_FROM_EDIT_NOT_IN_SYNC_NOTE = (
    "The cost no longer matches the amount paid from {account}, so the account was not changed."
)
PAID_FROM_EDIT_GONE_NOTE = "The account it was paid from no longer exists, so no money moved."


class PaidFromBody(BaseModel):
    # One of the user's active Cash & Savings accounts.
    cash_id: int
    # The sale or settlement whose proceeds are being reinvested (one of the user's exits).
    from_exit_id: int | None = None

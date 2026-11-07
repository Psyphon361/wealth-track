"""The optional `paid_from` of POST /api/assets/{type} ("Paid from" a Cash & Savings account).

The validation messages are shared verbatim with the web forms. "Choose one of your accounts" is
reused from schemas/exits.py.
"""

from pydantic import BaseModel

PAID_FROM_TOO_MUCH_ERROR = "More than this account's balance"
PAID_FROM_OTHER_AMOUNT_ERROR = "Enter the amount invested to pay it from an account"


class PaidFromBody(BaseModel):
    # One of the user's active Cash & Savings accounts.
    cash_id: int
    # The sale or settlement whose proceeds are being reinvested (one of the user's exits).
    from_exit_id: int | None = None

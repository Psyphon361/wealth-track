"""Duplicate-holding warnings for POST /api/assets/{type}.

A new holding is compared with the user's active (not soft-deleted) holdings of the same type,
using the values the create path will store (after master lookups). A match never blocks: the
caller may repeat the request with `confirm_duplicate=true`.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

DUPLICATE_MESSAGE = "This looks like a holding you already have"

_CASH_KINDS = {
    "savings": "Savings account",
    "current": "Current account",
    "cash": "Cash in hand",
    "other": "Other account",
}


def _text(value) -> str:
    return (value or "").strip().lower()


def _same_ref(new_id, old_id, new_name, old_name) -> bool:
    """Same master record when both are linked, else the same name (case-insensitive)."""
    if new_id is not None and old_id is not None:
        return new_id == old_id
    return _text(new_name) == _text(old_name)


def _same_fields(new: dict, old, *fields: str) -> bool:
    return all(new[field] == getattr(old, field) for field in fields)


def _matches(slug: str, new: dict, old) -> bool:
    if slug == "fd":
        return (
            _text(new["bank"]) == _text(old.bank)
            and new["principal"] == old.principal
            and new["start_date"] == old.start_date
        )
    if slug == "rd":
        return (
            _text(new["bank"]) == _text(old.bank)
            and new["monthly_instalment"] == old.monthly_instalment
            and new["start_date"] == old.start_date
        )
    if slug == "stock":
        return (
            _same_ref(new.get("master_id"), old.master_id, new["name"], old.name)
            and new["quantity"] == old.quantity
            and new["buy_date"] == old.buy_date
        )
    if slug == "bond":
        return (
            _same_ref(new.get("master_id"), old.master_id, new["name"], old.name)
            and new["quantity"] == old.quantity
            and new["purchase_date"] == old.purchase_date
        )
    if slug == "mf":
        return (
            _same_ref(new.get("scheme_code"), old.scheme_code, new["scheme_name"], old.scheme_name)
            and new["units"] == old.units
            and new["purchase_date"] == old.purchase_date
        )
    if slug == "nps":
        return _same_fields(new, old, "scheme_id", "start_date")
    if slug == "gold":
        return _same_fields(
            new, old, "metal", "form", "purity", "weight_grams", "purchase_date"
        )
    if slug == "cash":
        return _text(new["name"]) == _text(old.name) and new["kind"] == old.kind
    if slug == "pf":
        return new["kind"] == old.kind and _text(new["name"]) == _text(old.name)
    if slug == "other":
        return _text(new["name"]) == _text(old.name) and _text(new["category"]) == _text(
            old.category
        )
    return False


def find_duplicates(db: Session, slug: str, model, user_id: int, values: dict) -> list:
    """The user's active holdings of this type that look the same as `values`, oldest first.

    Holdings that were sold (closed_on set) are not compared: buying again after a sale is normal."""
    rows = db.scalars(
        select(model).where(model.user_id == user_id).order_by(model.id)
    ).all()
    return [
        row
        for row in rows
        if getattr(row, "closed_on", None) is None and _matches(slug, values, row)
    ]


def holding_name(obj) -> str:
    """Display name of a holding, as shown elsewhere in the API messages."""
    if hasattr(obj, "bank"):
        return f"{obj.bank} · {obj.label}" if obj.label else obj.bank
    if hasattr(obj, "scheme_name"):
        return obj.scheme_name
    if hasattr(obj, "master"):
        return obj.master.scheme_name
    return obj.name


def format_inr(amount: Decimal | int | float) -> str:
    """Indian grouping with the rupee sign: 100000 -> ₹1,00,000; 1234.5 -> ₹1,234.50."""
    value = Decimal(str(amount)).quantize(Decimal("0.01"))
    whole, _, paise = f"{abs(value):.2f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join([*groups, tail])
    text = whole if paise == "00" else f"{whole}.{paise}"
    return f"{'-' if value < 0 else ''}₹{text}"


def format_date(value: date) -> str:
    return f"{value.day} {value:%b %Y}"


def _number(value: Decimal | int) -> str:
    text = f"{value:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def key_facts(slug: str, obj) -> str:
    """Short plain summary of the fields that made two holdings match."""
    if slug == "fd":
        return f"{format_inr(obj.principal)} from {format_date(obj.start_date)}"
    if slug == "rd":
        return f"{format_inr(obj.monthly_instalment)} a month from {format_date(obj.start_date)}"
    if slug == "stock":
        return f"{_plural(obj.quantity, 'share', 'shares')} bought {format_date(obj.buy_date)}"
    if slug == "bond":
        return f"{_plural(obj.quantity, 'bond', 'bonds')} bought {format_date(obj.purchase_date)}"
    if slug == "mf":
        return f"{_number(obj.units)} units bought {format_date(obj.purchase_date)}"
    if slug == "nps":
        return f"started {format_date(obj.start_date)}"
    if slug == "gold":
        return (
            f"{_number(obj.weight_grams)} g {obj.metal} {obj.purity} "
            f"bought {format_date(obj.purchase_date)}"
        )
    if slug == "cash":
        return _CASH_KINDS.get(obj.kind, obj.kind.capitalize())
    if slug == "pf":
        return obj.kind.upper()
    return obj.category


def duplicate_body(slug: str, matches: list) -> dict:
    """The 409 body: message, description and the matching holdings as {id, name}."""
    first = matches[0]
    subject = f"{holding_name(first)} · {key_facts(slug, first)}"
    if len(matches) == 1:
        description = f"{subject} is already in your portfolio."
    else:
        description = f"{subject} and {len(matches) - 1} more are already in your portfolio."
    return {
        "message": DUPLICATE_MESSAGE,
        "description": description,
        "duplicates": [{"id": m.id, "name": holding_name(m)} for m in matches],
    }

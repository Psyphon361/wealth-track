from datetime import date, datetime

from pydantic import BaseModel


class DeletedHolding(BaseModel):
    type: str
    type_label: str
    id: int
    name: str
    deleted_at: datetime
    purge_on: date
    days_left: int

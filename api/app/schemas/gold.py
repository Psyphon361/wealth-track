from datetime import date

from pydantic import BaseModel


class GoldImportResult(BaseModel):
    rate_date: date
    session: str
    rows_upserted: int

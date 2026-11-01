from datetime import date

from pydantic import BaseModel


class NpsImportResult(BaseModel):
    rows: int
    active: int
    inactive: int
    file_date: date | None = None
    inserted: int
    updated: int
    unchanged: int
    deactivated: int
    navs_upserted: int
    history_appended: int = 0
    history_synced: int = 0

from pydantic import BaseModel


class Outcome(BaseModel):
    """User-facing text describing the result of an operation."""

    message: str
    description: str

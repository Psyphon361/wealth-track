from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    succeeded: Mapped[bool] = mapped_column(Boolean)

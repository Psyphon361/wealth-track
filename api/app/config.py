from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str | None = None
    cors_origins: list[str] = ["http://localhost:3000"]
    api_key: str | None = None
    cron_secret: str | None = None
    jwt_secret: str | None = None
    allowed_emails: Annotated[list[str], NoDecode] = []
    owner_email: str | None = None

    @field_validator("api_key", "cron_secret", "jwt_secret", "owner_email")
    @classmethod
    def empty_api_key_is_none(cls, value: str | None) -> str | None:
        return value or None

    @field_validator("allowed_emails", mode="before")
    @classmethod
    def split_allowed_emails(cls, value: object) -> object:
        """Accept a comma-separated string; trim and lower-case each entry."""
        if isinstance(value, str):
            value = value.split(",")
        if isinstance(value, (list, tuple)):
            return [str(item).strip().lower() for item in value if str(item).strip()]
        return value

    @field_validator("database_url")
    @classmethod
    def normalise_database_url(cls, value: str | None) -> str | None:
        """Force the psycopg 3 driver, e.g. for Neon's postgresql:// URLs."""
        if value is None:
            return None
        for prefix in ("postgresql://", "postgres://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix):]
        return value


settings = Settings()

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RelaySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RELAY_", env_file=".env", extra="ignore")

    application_id: str
    bot_token: str = Field(repr=False)
    bind_host: str = "0.0.0.0"  # noqa: S104 - public relay listener
    port: int = Field(default=8080, ge=1, le=65535)
    database_path: Path = Path("relay-data/relay.db")
    stale_after_seconds: int = Field(default=180, ge=30, le=86400)
    tls_cert_file: Path | None = None
    tls_key_file: Path | None = Field(default=None, repr=False)

    @field_validator("application_id")
    @classmethod
    def application_id_is_numeric(cls, value: str) -> str:
        candidate = value.strip()
        if not candidate.isdigit() or not 17 <= len(candidate) <= 20:
            raise ValueError("RELAY_APPLICATION_ID must be a Discord application ID")
        return candidate

    @field_validator("bot_token")
    @classmethod
    def token_is_present(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("RELAY_BOT_TOKEN is required")
        return value.strip()

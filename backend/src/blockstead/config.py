from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BLOCKSTEAD_", env_file=".env", extra="ignore")
    bind_host: str = "127.0.0.1"
    port: int = 8765
    data_dir: Path = Path("data")
    server_root: Path = Path("fixtures/servers")
    secure_cookies: bool = False
    allowed_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    session_hours: int = Field(default=12, ge=1)
    #: Built dashboard to serve. Left unset, Blockstead looks for it in the source
    #: checkout and next to an installed virtual environment.
    static_dir: Path | None = None

    @field_validator("bind_host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        if value not in {"127.0.0.1", "localhost", "::1", "0.0.0.0", "::"}:  # noqa: S104
            raise ValueError("bind_host must be loopback or an explicit all-interface bind")
        return value

    @property
    def origins(self) -> frozenset[str]:
        return frozenset(
            item.strip().rstrip("/") for item in self.allowed_origins.split(",") if item.strip()
        )

    def prepare(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.server_root.mkdir(parents=True, exist_ok=True)

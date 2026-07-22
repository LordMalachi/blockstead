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
    #: Install and keep the newest Blockstead without the owner doing anything.
    #: Turned off automatically when the machine has no privileged update helper,
    #: which is the case for development checkouts and Docker.
    update_auto: bool = True
    #: The GitHub repository Blockstead updates itself from, as "owner/name".
    #: The privileged helper hardcodes this too and ignores anything the
    #: application asks for, so changing it here alone cannot redirect an update.
    update_repo: str = "LordMalachi/blockstead"
    update_branch: str = "main"
    #: Promoted only after the configured branch passes its GitHub Actions
    #: checks. Installed copies never follow the live branch tip directly.
    update_manifest_url: str = (
        "https://github.com/LordMalachi/blockstead/releases/download/update-channel/latest.json"
    )
    #: Where the installer recorded the commit this copy was built from. Left
    #: unset, Blockstead looks beside the installed application.
    update_build_file: Path | None = None
    #: Durable progress owned by root and readable by the dashboard service.
    update_status_file: Path = Path("/var/lib/blockstead-update/status.json")
    #: An active helper status older than this no longer hides a stalled update.
    update_status_max_age_minutes: int = Field(default=60, ge=1)
    #: Poll helper progress promptly so an empty server can be resumed after the
    #: installer or rollback finishes.
    update_status_poll_seconds: float = Field(default=5.0, ge=0.1, le=300)
    #: How long to wait between update checks while the application keeps running.
    update_check_hours: int = Field(default=6, ge=1)
    #: Once an update is waiting for players to leave, check frequently instead
    #: of waiting for the normal six-hour channel interval.
    update_wait_minutes: float = Field(default=5.0, ge=0.1, le=60)

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

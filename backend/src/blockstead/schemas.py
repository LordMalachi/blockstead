import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .security import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH

PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ImportRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    path: str = Field(min_length=1, max_length=4096)


class ImportUploadStart(BaseModel):
    directory_name: str = Field(min_length=1, max_length=64)


class ImportUploadFinish(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    directory_name: str = Field(min_length=1, max_length=64)


class CommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=32767)

    @field_validator("command")
    @classmethod
    def one_line(cls, value: str) -> str:
        if any(c in value for c in "\r\n\x00"):
            raise ValueError("command must contain exactly one line")
        return value


class ProvisionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    directory_name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    distribution: str = Field(pattern=r"^(vanilla|paper|fabric|forge|quilt|neoforge)$")
    minecraft_version: str = Field(min_length=1, max_length=32, pattern=r"^[0-9][0-9A-Za-z._-]*$")
    loader_version: str | None = Field(
        default=None, max_length=64, pattern=r"^[0-9A-Za-z][0-9A-Za-z.+_-]*$"
    )


class EulaRequest(BaseModel):
    accept: bool


class BackupPolicyRequest(BaseModel):
    """Retention rules; null disables a rule rather than meaning zero."""

    keep_count: int | None = Field(default=None, ge=1, le=500)
    keep_days: int | None = Field(default=None, ge=1, le=3650)
    max_total_mb: int | None = Field(default=None, ge=100, le=10_000_000)
    redundancy_enabled: bool = False
    destinations: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("destinations")
    @classmethod
    def valid_backup_destinations(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            value = value.strip()
            if not value or len(value) > 4096 or "\x00" in value:
                raise ValueError("Each backup destination must be a usable folder path.")
            if value not in cleaned:
                cleaned.append(value)
        return cleaned


class InstallRequest(BaseModel):
    """Catalog installs; the API re-validates project_id per source."""

    project_id: str = Field(
        min_length=1, max_length=104, pattern=r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?$"
    )
    version_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9._+-]+$")
    source: Literal["modrinth", "hangar", "curseforge"] = "modrinth"


class CurseForgeKeyRequest(BaseModel):
    """The owner's own CurseForge core API key; stored, never echoed back."""

    api_key: str = Field(min_length=8, max_length=256, pattern=r"^\S+$")


class ToggleRequest(BaseModel):
    file_name: str = Field(min_length=5, max_length=132)
    enabled: bool


class ToggleAllRequest(BaseModel):
    enabled: bool


class UpdateRequest(BaseModel):
    file_name: str = Field(min_length=5, max_length=132)


class ModConfigUpdateRequest(BaseModel):
    path: str = Field(min_length=1, max_length=512)
    revision: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    content: str = Field(max_length=1_000_000)


class ModpackInstallRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    directory_name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    project_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    version_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class StartRequest(BaseModel):
    profile_id: str = Field(default="", max_length=36)
    mode: str = Field(default="normal", pattern=r"^(normal|slow|ignore-stop|crash)$")


class ScheduleRequest(BaseModel):
    profile_id: str = Field(max_length=36)
    enabled: bool = True
    start_time: str | None = Field(default=None, pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
    stop_time: str | None = Field(default=None, pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
    backup_before_stop: bool = True
    power_off_after_stop: bool = False
    wake_time: str | None = Field(default=None, pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
    weekdays: list[int] = Field(default_factory=lambda: list(range(7)), min_length=1, max_length=7)
    only_when_empty: bool = False

    @field_validator("weekdays")
    @classmethod
    def valid_weekdays(cls, value: list[int]) -> list[int]:
        if any(day < 0 or day > 6 for day in value) or len(value) != len(set(value)):
            raise ValueError("weekdays must be unique numbers from 0 through 6")
        return sorted(value)


class AutomationEventRequest(BaseModel):
    run_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T([01][0-9]|2[0-3]):[0-5][0-9]$")
    backup_before_stop: bool = True
    power_off_after_stop: bool = False
    wake_time: str | None = Field(default=None, pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
    only_when_empty: bool = False

    @field_validator("run_at")
    @classmethod
    def valid_local_datetime(cls, value: str) -> str:
        from datetime import datetime

        try:
            datetime.strptime(value, "%Y-%m-%dT%H:%M")
        except ValueError as exc:
            raise ValueError("run_at must be a real local date and time") from exc
        return value


class AutomationRunRequest(BaseModel):
    action: str = Field(default="maintenance", pattern=r"^(start|maintenance)$")
    confirm_power: bool = False


class NotificationPreferencesRequest(BaseModel):
    server_crashes: bool = True
    failed_backups: bool = True
    low_disk_space: bool = True
    completed_updates: bool = True
    show_player_avatars: bool = False


class SettingChangeRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")
    value: str | int | bool


class RawSettingsUpdateRequest(BaseModel):
    revision: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    content: str = Field(max_length=1_000_000)


class SettingsUpdateRequest(BaseModel):
    revision: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    changes: list[SettingChangeRequest] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def unique_keys(self) -> "SettingsUpdateRequest":
        keys = [change.key for change in self.changes]
        if len(keys) != len(set(keys)):
            raise ValueError("setting changes must use unique keys")
        return self


class FileEditRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    revision: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    content: str = Field(max_length=1_000_000)


class FileRenameRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    new_name: str = Field(min_length=1, max_length=255)


PLAYER_ACTIONS: dict[str, str] = {
    "whitelist_add": "whitelist add",
    "whitelist_remove": "whitelist remove",
    "op": "op",
    "deop": "deop",
    "ban": "ban",
    "pardon": "pardon",
    "kick": "kick",
}


class PlayerActionRequest(BaseModel):
    action: str = Field(pattern=r"^(whitelist_add|whitelist_remove|op|deop|ban|pardon|kick)$")
    player: str = Field(pattern=r"^[A-Za-z0-9_]{3,16}$")

    @property
    def console_command(self) -> str:
        return f"{PLAYER_ACTIONS[self.action]} {self.player}"

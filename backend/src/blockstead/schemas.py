from pydantic import BaseModel, Field, field_validator


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=256)


class ImportRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    path: str = Field(min_length=1, max_length=4096)


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
    distribution: str = Field(pattern=r"^(vanilla|paper|fabric|neoforge)$")
    minecraft_version: str = Field(min_length=1, max_length=32, pattern=r"^[0-9][0-9A-Za-z._-]*$")


class EulaRequest(BaseModel):
    accept: bool


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


PLAYER_ACTIONS: dict[str, str] = {
    "whitelist_add": "whitelist add",
    "whitelist_remove": "whitelist remove",
    "op": "op",
    "deop": "deop",
    "ban": "ban",
    "pardon": "pardon",
}


class PlayerActionRequest(BaseModel):
    action: str = Field(pattern=r"^(whitelist_add|whitelist_remove|op|deop|ban|pardon)$")
    player: str = Field(pattern=r"^[A-Za-z0-9_]{3,16}$")

    @property
    def console_command(self) -> str:
        return f"{PLAYER_ACTIONS[self.action]} {self.player}"

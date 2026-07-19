"""Owner-facing overview helpers for one managed Minecraft profile."""

import asyncio
import ipaddress
import json
import re
import socket
import struct
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import psutil

MAX_STATUS_BYTES = 1_000_000
MAX_PROPERTIES_BYTES = 1_000_000
_LEVEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


def read_properties(server_directory: Path) -> dict[str, str]:
    """Read a bounded server.properties file without exposing values to the caller."""

    path = server_directory / "server.properties"
    try:
        if not path.is_file() or path.stat().st_size > MAX_PROPERTIES_BYTES:
            return {}
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "!")) or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def integer_property(
    values: dict[str, str], key: str, default: int, minimum: int, maximum: int
) -> int:
    try:
        value = int(values.get(key, str(default)))
    except ValueError:
        return default
    return value if minimum <= value <= maximum else default


def world_size(server_directory: Path, values: dict[str, str] | None = None) -> int | None:
    """Return the byte size of recognized world folders, excluding links."""

    values = values if values is not None else read_properties(server_directory)
    prefixes = {"world"}
    level_name = values.get("level-name", "")
    if _LEVEL_NAME.fullmatch(level_name):
        prefixes.add(level_name)
    try:
        roots = {
            path
            for prefix in prefixes
            for path in server_directory.glob(f"{prefix}*")
            if path.is_dir() and not path.is_symlink()
        }
    except OSError:
        return None
    if not roots:
        return None
    total = 0
    for root in roots:
        try:
            for path in root.rglob("*"):
                if path.is_file() and not path.is_symlink():
                    total += path.stat().st_size
        except OSError:
            # A live server may replace a file between traversal and stat. Keep
            # the useful partial measurement instead of failing the overview.
            continue
    return total


def _lan_addresses() -> list[str]:
    addresses: set[str] = set()
    for entries in psutil.net_if_addrs().values():
        for entry in entries:
            if entry.family not in {socket.AF_INET, socket.AF_INET6}:
                continue
            raw = entry.address.split("%", 1)[0]
            try:
                address = ipaddress.ip_address(raw)
            except ValueError:
                continue
            if address.is_loopback or address.is_link_local or address.is_unspecified:
                continue
            addresses.add(str(address))
    return sorted(addresses, key=lambda item: (ipaddress.ip_address(item).version, item))


def join_details(values: dict[str, str], request_host: str | None) -> dict[str, object]:
    """Describe where players can join without claiming router reachability."""

    port = integer_property(values, "server-port", 25565, 1, 65535)
    bind = values.get("server-ip", "").strip()
    wildcard = bind in {"", "0.0.0.0", "::"}  # noqa: S104 -- detecting MC wildcard
    local_only = bind in {"127.0.0.1", "::1", "localhost"}
    candidates = _lan_addresses() if wildcard else []
    host = bind
    if wildcard:
        request_host = (request_host or "").strip("[]")
        try:
            request_address = ipaddress.ip_address(request_host)
        except ValueError:
            request_address = None
        if request_host and not (request_address and request_address.is_loopback):
            host = request_host
        elif candidates:
            host = candidates[0]
        else:
            host = request_host or "localhost"
    display_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return {
        "host": host,
        "port": port,
        "address": f"{display_host}:{port}",
        "bind_address": bind or None,
        "candidate_hosts": candidates,
        "local_only": local_only,
    }


def _varint(value: int) -> bytes:
    encoded = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        encoded.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(encoded)


async def _read_varint(reader: asyncio.StreamReader) -> int:
    value = 0
    for shift in range(0, 35, 7):
        byte = (await reader.readexactly(1))[0]
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value
    raise ValueError("Minecraft status VarInt was too long")


async def minecraft_status(values: dict[str, str]) -> dict[str, object] | None:
    """Probe the local Java status protocol, returning only trusted fields."""

    bind = values.get("server-ip", "").strip()
    if bind in {"", "0.0.0.0"}:  # noqa: S104 -- probing a wildcard-bound MC server
        target = "127.0.0.1"
    elif bind == "::":
        target = "::1"
    elif bind == "localhost":
        target = bind
    else:
        try:
            ipaddress.ip_address(bind)
        except ValueError:
            return None
        target = bind
    port = integer_property(values, "server-port", 25565, 1, 65535)
    writer: asyncio.StreamWriter | None = None
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(target, port), 1.0)
        assert writer is not None
        address = target.encode("utf-8")
        handshake = _varint(0) + _varint(0) + _varint(len(address)) + address
        handshake += struct.pack(">H", port) + _varint(1)
        writer.write(_varint(len(handshake)) + handshake + b"\x01\x00")
        await writer.drain()
        packet_length = await asyncio.wait_for(_read_varint(reader), 1.0)
        if packet_length < 1 or packet_length > MAX_STATUS_BYTES:
            return None
        packet_id = await _read_varint(reader)
        if packet_id != 0:
            return None
        payload_length = await _read_varint(reader)
        if payload_length < 2 or payload_length > MAX_STATUS_BYTES:
            return None
        raw = await reader.readexactly(payload_length)
        payload: Any = json.loads(raw.decode("utf-8"))
        players = payload.get("players") if isinstance(payload, dict) else None
        if not isinstance(players, dict):
            return None
        online = players.get("online")
        maximum = players.get("max")
        if not isinstance(online, int) or not isinstance(maximum, int):
            return None
        sample = players.get("sample")
        names = []
        if isinstance(sample, list):
            names = [
                entry["name"][:64]
                for entry in sample[:100]
                if isinstance(entry, dict) and isinstance(entry.get("name"), str)
            ]
        return {"online": max(0, online), "max": max(0, maximum), "sample": names}
    except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError, TimeoutError):
        return None
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass


def next_schedule_operation(
    enabled: bool, start_time: str | None, stop_time: str | None, now: datetime
) -> dict[str, str] | None:
    if not enabled:
        return None
    candidates: list[tuple[datetime, str]] = []
    for label, value in (("Start server", start_time), ("Back up and stop", stop_time)):
        if not value:
            continue
        hour, minute = (int(part) for part in value.split(":"))
        when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if when <= now:
            when += timedelta(days=1)
        candidates.append((when, label))
    if not candidates:
        return None
    when, label = min(candidates, key=lambda item: item[0])
    return {"label": label, "at": when.isoformat()}

"""Owner-facing overview helpers for one managed Minecraft profile."""

import asyncio
import ipaddress
import json
import re
import socket
import struct
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import psutil

MAX_STATUS_BYTES = 1_000_000
MAX_PROPERTIES_BYTES = 1_000_000
_LEVEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
PUBLIC_IP_DISCOVERY_URL = "https://api64.ipify.org?format=json"
PUBLIC_IP_CACHE_SECONDS = 300.0
PUBLIC_IP_FAILURE_CACHE_SECONDS = 15.0


class PublicIpDiscovery:
    """Bounded, cached public-IP lookup with no configured endpoint fallback."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._now = now
        self._cached: dict[str, object] | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def discover(self, *, force: bool = False) -> dict[str, object]:
        """Return only a validated public IP or an owner-safe failure detail."""

        now = self._now()
        if not force and self._cached is not None and now < self._expires_at:
            return self._cached
        async with self._lock:
            now = self._now()
            if not force and self._cached is not None and now < self._expires_at:
                return self._cached
            try:
                response = await self._client.get(
                    PUBLIC_IP_DISCOVERY_URL,
                    headers={"Accept": "application/json"},
                    timeout=httpx.Timeout(3.0),
                )
                response.raise_for_status()
                body = response.json()
                candidate = body.get("ip") if isinstance(body, dict) else None
                if not isinstance(candidate, str):
                    raise ValueError("The public-IP service returned no IP address.")
                address = ipaddress.ip_address(candidate.strip())
                if not address.is_global:
                    raise ValueError("The public-IP service returned a non-public address.")
                result: dict[str, object] = {
                    "available": True,
                    "ip": str(address),
                    "detail": (
                        "Blockstead detected this network's public IP. It cannot "
                        "verify the router-facing Minecraft port from inside the network."
                    ),
                }
                ttl = PUBLIC_IP_CACHE_SECONDS
            except (httpx.HTTPError, ValueError, TypeError):
                result = {
                    "available": False,
                    "ip": None,
                    "detail": (
                        "Blockstead could not detect this network's public IP. "
                        "No public Minecraft address is being shown."
                    ),
                }
                ttl = PUBLIC_IP_FAILURE_CACHE_SECONDS
            self._cached = result
            self._expires_at = self._now() + ttl
            return result


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


def join_details(
    values: dict[str, str],
    public_ip: dict[str, object],
) -> dict[str, object]:
    """Describe LAN access and public-IP discovery without inventing an endpoint."""

    port = integer_property(values, "server-port", 25565, 1, 65535)
    bind = values.get("server-ip", "").strip()
    wildcard = bind in {"", "0.0.0.0", "::"}  # noqa: S104 -- detecting MC wildcard
    local_only = bind in {"127.0.0.1", "::1", "localhost"}
    candidates = _lan_addresses() if wildcard else []
    host: str | None = bind or None
    if wildcard:
        host = candidates[0] if candidates else None
    display_host = f"[{host}]" if host and ":" in host and not host.startswith("[") else host
    public_available = public_ip.get("available") is True
    detected_ip = public_ip.get("ip") if isinstance(public_ip.get("ip"), str) else None
    if not public_available:
        public_state = "unavailable"
    elif local_only:
        public_state = "local_only"
    else:
        # NAT, firewall, and Docker mappings cannot reliably be learned by the
        # host itself. Never turn an IP plus local listening port into a claimed
        # public Minecraft address without an external reachability check.
        public_state = "port_unverified"
    return {
        "host": host,
        "port": port,
        "address": f"{display_host}:{port}" if display_host else None,
        "bind_address": bind or None,
        "candidate_hosts": candidates,
        "local_only": local_only,
        "public": {
            "state": public_state,
            "detected_ip": detected_ip,
            "server_port": port,
            "address": None,
            "detail": str(public_ip["detail"]),
        },
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

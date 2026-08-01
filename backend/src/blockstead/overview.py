"""Owner-facing overview helpers for one managed Minecraft profile."""

import asyncio
import ipaddress
import json
import re
import socket
import struct
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TypedDict

import httpx
import psutil

MAX_STATUS_BYTES = 1_000_000
MAX_PROPERTIES_BYTES = 1_000_000
_LEVEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
PUBLIC_IP_DISCOVERY_URL = "https://api64.ipify.org?format=json"
PUBLIC_IP_CACHE_SECONDS = 300.0
PUBLIC_IP_FAILURE_CACHE_SECONDS = 15.0


class PublicJoinDetails(TypedDict):
    """Public-connection information that deliberately avoids a claimed endpoint."""

    state: str
    detected_ip: str | None
    server_port: int
    address: None
    detail: str


class JoinDetails(TypedDict):
    """Owner-facing Minecraft connection information for one profile."""

    host: str | None
    port: int
    address: str | None
    bind_address: str | None
    candidate_hosts: list[str]
    local_only: bool
    public: PublicJoinDetails


class MinecraftStatusProbe(TypedDict):
    """Structured result for an optional Minecraft server-list status request."""

    outcome: str
    detail: str
    tcp_connected: bool | None
    status: dict[str, object] | None


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
                    "outcome": "detected",
                    "checked_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
                    "detail": (
                        "Blockstead detected this network's public IP. It cannot "
                        "verify the router-facing Minecraft port from inside the network."
                    ),
                }
                ttl = PUBLIC_IP_CACHE_SECONDS
            except httpx.TimeoutException:
                result = {
                    "available": False,
                    "ip": None,
                    "outcome": "timeout",
                    "checked_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
                    "detail": (
                        "Blockstead's public-IP lookup timed out. No public Minecraft "
                        "address is being shown."
                    ),
                }
                ttl = PUBLIC_IP_FAILURE_CACHE_SECONDS
            except httpx.HTTPError:
                result = {
                    "available": False,
                    "ip": None,
                    "outcome": "network_error",
                    "checked_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
                    "detail": (
                        "Blockstead could not reach its public-IP service. No public "
                        "Minecraft address is being shown."
                    ),
                }
                ttl = PUBLIC_IP_FAILURE_CACHE_SECONDS
            except (ValueError, TypeError):
                result = {
                    "available": False,
                    "ip": None,
                    "outcome": "invalid_response",
                    "checked_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
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


def _measure_world(
    server_directory: Path, values: dict[str, str] | None, *, strict: bool
) -> int | None:
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
            # A live server may replace a file between traversal and stat.
            if strict:
                return None
            # Keep the useful partial measurement instead of failing the overview.
            continue
    return total


def world_size(server_directory: Path, values: dict[str, str] | None = None) -> int | None:
    """Byte size of recognized world folders, excluding links.

    Tolerant by design: a file that disappears mid-scan yields a partial total
    rather than nothing, which is what the overview's size display wants.
    """

    return _measure_world(server_directory, values, strict=False)


def strict_world_size(server_directory: Path, values: dict[str, str] | None = None) -> int | None:
    """Byte size of recognized world folders, or None if anything was unreadable.

    A safety estimate must not silently shrink. Any traversal or stat error
    makes the whole measurement unknown, so a caller sizing a backup against
    free disk reports "could not check" instead of "it fits".
    """

    return _measure_world(server_directory, values, strict=True)


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
) -> JoinDetails:
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
    possible_ip = public_ip.get("ip")
    detected_ip = possible_ip if isinstance(possible_ip, str) else None
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


def status_protocol_enabled(values: dict[str, str]) -> bool:
    """Whether server.properties permits the optional server-list status reply."""

    return values.get("enable-status", "true").strip().casefold() != "false"


async def minecraft_status_probe(values: dict[str, str]) -> MinecraftStatusProbe:
    """Probe local Java status without treating optional metadata as server health."""

    if not status_protocol_enabled(values):
        return {
            "outcome": "disabled",
            "detail": (
                "server.properties has enable-status=false. Players may still connect, "
                "but Minecraft intentionally withholds server-list and player-count data."
            ),
            "tcp_connected": None,
            "status": None,
        }

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
            return {
                "outcome": "invalid_bind",
                "detail": "server-ip is not a valid local address, so Blockstead did not probe it.",
                "tcp_connected": None,
                "status": None,
            }
        target = bind
    port = integer_property(values, "server-port", 25565, 1, 65535)
    writer: asyncio.StreamWriter | None = None
    try:
        async with asyncio.timeout(2.0):
            reader, writer = await asyncio.open_connection(target, port)
            address = target.encode("utf-8")
            handshake = _varint(0) + _varint(0) + _varint(len(address)) + address
            handshake += struct.pack(">H", port) + _varint(1)
            writer.write(_varint(len(handshake)) + handshake + b"\x01\x00")
            await writer.drain()
            packet_length = await _read_varint(reader)
            if packet_length < 1 or packet_length > MAX_STATUS_BYTES:
                raise ValueError("Minecraft status packet length was invalid")
            packet_id = await _read_varint(reader)
            if packet_id != 0:
                raise ValueError("Minecraft status packet id was invalid")
            payload_length = await _read_varint(reader)
            if payload_length < 2 or payload_length > MAX_STATUS_BYTES:
                raise ValueError("Minecraft status payload length was invalid")
            raw = await reader.readexactly(payload_length)
            payload: Any = json.loads(raw.decode("utf-8"))
            players = payload.get("players") if isinstance(payload, dict) else None
            if not isinstance(players, dict):
                raise ValueError("Minecraft status response contained no player information")
            online = players.get("online")
            maximum = players.get("max")
            if not isinstance(online, int) or not isinstance(maximum, int):
                raise ValueError("Minecraft status player counts were invalid")
            sample = players.get("sample")
            names = []
            if isinstance(sample, list):
                names = [
                    entry["name"][:64]
                    for entry in sample[:100]
                    if isinstance(entry, dict) and isinstance(entry.get("name"), str)
                ]
            status = {"online": max(0, online), "max": max(0, maximum), "sample": names}
            return {
                "outcome": "responded",
                "detail": "Minecraft returned a valid local server-list status response.",
                "tcp_connected": True,
                "status": status,
            }
    except asyncio.IncompleteReadError:
        return {
            "outcome": "closed_early",
            "detail": (
                "Minecraft accepted the local TCP connection but closed it before returning "
                "server-list status data. This does not by itself mean players cannot join."
            ),
            "tcp_connected": True,
            "status": None,
        }
    except TimeoutError:
        return {
            "outcome": "timeout",
            "detail": "The bounded local Minecraft status request timed out.",
            "tcp_connected": writer is not None,
            "status": None,
        }
    except OSError:
        return {
            "outcome": "unreachable",
            "detail": "Blockstead could not open the configured local Minecraft TCP port.",
            "tcp_connected": False,
            "status": None,
        }
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return {
            "outcome": "invalid_response",
            "detail": "Minecraft returned an incomplete or invalid local status response.",
            "tcp_connected": True,
            "status": None,
        }
    finally:
        if writer is not None:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 0.25)
            except (OSError, TimeoutError):
                pass


async def minecraft_status(values: dict[str, str]) -> dict[str, object] | None:
    """Compatibility wrapper returning only trusted player fields when available."""

    return (await minecraft_status_probe(values))["status"]


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

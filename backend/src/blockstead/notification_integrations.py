"""Safe Discord-compatible webhook validation and payload handling."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from urllib.parse import urlsplit

import httpx

from .diagnostics import redact

ALERT_KINDS = frozenset(
    {"server_crash", "failed_backup", "failed_automation", "low_disk_space", "completed_update"}
)
_IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV6_PATTERN = re.compile(
    r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![0-9A-Fa-f:])"
)
_PATH_PATTERN = re.compile(r"(?:(?:[A-Za-z]:[\\/])|/)[^\s,;]+")


class WebhookValidationError(ValueError):
    """A webhook URL is not a safe public Discord-compatible destination."""


def validate_webhook_url(value: str) -> str:
    url = value.strip()
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise WebhookValidationError(
            "Use an HTTPS Discord webhook URL without credentials or query parameters."
        )
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if hostname not in {"discord.com", "discordapp.com", "canary.discord.com", "ptb.discord.com"}:
        raise WebhookValidationError("The webhook must be hosted by Discord.")
    if not parsed.path.startswith("/api/webhooks/"):
        raise WebhookValidationError("That URL is not a Discord webhook endpoint.")
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        }
    except OSError as exc:
        raise WebhookValidationError(
            "Blockstead could not resolve that webhook host safely."
        ) from exc
    if not addresses:
        raise WebhookValidationError("Blockstead could not resolve that webhook host safely.")
    for address in addresses:
        parsed_address = ipaddress.ip_address(address)
        if (
            parsed_address.is_private
            or parsed_address.is_loopback
            or parsed_address.is_link_local
            or parsed_address.is_multicast
            or parsed_address.is_unspecified
            or parsed_address.is_reserved
        ):
            raise WebhookValidationError("The webhook host resolved to a non-public address.")
    return url


def safe_payload(alert: dict[str, object]) -> dict[str, object]:
    """Build the only shape allowed to leave Blockstead for an alert."""
    detail = redact(str(alert.get("detail") or ""))
    detail = _IP_PATTERN.sub("[redacted address]", detail)
    detail = _IPV6_PATTERN.sub("[redacted address]", detail)
    detail = _PATH_PATTERN.sub("[redacted path]", detail)
    return {
        "title": str(alert.get("title") or "Blockstead alert"),
        "severity": str(alert.get("severity") or "warning"),
        "detail": detail[:1500],
        "created_at": str(alert.get("created_at") or ""),
        "recovery_to": str(alert.get("recovery_to") or "/servers"),
    }


def discord_body(payload: dict[str, object]) -> dict[str, str]:
    content = (
        f"**Blockstead · {payload['severity']}**\n"
        f"**{payload['title']}**\n{payload['detail']}\n"
        f"Recovery: {payload['recovery_to']}"
    )
    return {"content": content[:1900]}


async def send_discord(webhook_url: str, payload: dict[str, object]) -> tuple[int, str]:
    """Send one bounded, redirect-free delivery and return safe status detail."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0), follow_redirects=False) as client:
        response = await client.post(webhook_url, json=discord_body(payload))
    if 200 <= response.status_code < 300:
        return response.status_code, "Discord accepted the delivery."
    if response.status_code in {429, 500, 502, 503, 504}:
        return response.status_code, "Discord temporarily rejected the delivery; retrying."
    return response.status_code, "Discord rejected the delivery; review the webhook configuration."


def serialize_payload(payload: dict[str, object]) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)

"""Capability-gated Paper performance command parsing.

Paper exposes lightweight tick evidence through the ``tps`` and ``mspt``
console commands. The parser intentionally accepts only the labelled output
shape, so an unrelated plugin log line can never be presented as a reading.
"""

import re
from typing import Literal, TypedDict

PAPER_PERFORMANCE_DISTRIBUTIONS = frozenset({"paper"})
PERFORMANCE_SOURCE = "Paper console /tps and /mspt commands"
PERFORMANCE_SAMPLING_PERIOD_SECONDS = 60

_NUMBER = r"(?:\d+(?:\.\d+)?|\.\d+)"
_TPS_LINE = re.compile(r"\bTPS\s+from\s+last\s+(.+?):\s*(.+)$", re.IGNORECASE)
_MSPT_LINE = re.compile(r"\bMSPT\s+from\s+last\s+(.+?):\s*(.+)$", re.IGNORECASE)


class TpsValues(TypedDict):
    one_minute: float | None
    five_minutes: float | None
    fifteen_minutes: float | None


class MsptValues(TypedDict):
    five_seconds: float | None
    ten_seconds: float | None
    sixty_seconds: float | None


def empty_tps() -> TpsValues:
    return {"one_minute": None, "five_minutes": None, "fifteen_minutes": None}


def empty_mspt() -> MsptValues:
    return {"five_seconds": None, "ten_seconds": None, "sixty_seconds": None}


def _period_key(period: str) -> str:
    return re.sub(r"[^0-9a-z]", "", period.casefold())


def _numbers(text: str) -> list[float]:
    return [float(value) for value in re.findall(rf"\*?({_NUMBER})", text)]


def parse_paper_tps(line: str) -> TpsValues | None:
    """Parse a Paper ``tps`` line, including starred warming-up values."""

    match = _TPS_LINE.search(line)
    if match is None:
        return None
    periods = [part.strip() for part in match.group(1).split(",")]
    values = _numbers(match.group(2))
    result = empty_tps()
    mapped = False
    names: dict[str, Literal["one_minute", "five_minutes", "fifteen_minutes"]] = {
        "1m": "one_minute",
        "60s": "one_minute",
        "5m": "five_minutes",
        "15m": "fifteen_minutes",
    }
    for period, value in zip(periods, values, strict=False):
        name = names.get(_period_key(period))
        if name is not None:
            result[name] = value
            mapped = True
    return result if mapped else None


def parse_paper_mspt(line: str) -> MsptValues | None:
    """Parse a Paper ``mspt`` line into its average windows."""

    match = _MSPT_LINE.search(line)
    if match is None:
        return None
    periods = [part.strip() for part in match.group(1).split(",")]
    values = _numbers(match.group(2))
    result = empty_mspt()
    mapped = False
    names: dict[str, Literal["five_seconds", "ten_seconds", "sixty_seconds"]] = {
        "5s": "five_seconds",
        "10s": "ten_seconds",
        "60s": "sixty_seconds",
        "1m": "sixty_seconds",
    }
    for period, value in zip(periods, values, strict=False):
        name = names.get(_period_key(period))
        if name is not None:
            result[name] = value
            mapped = True
    return result if mapped else None


def parse_paper_performance(lines: list[str]) -> tuple[TpsValues | None, MsptValues | None]:
    """Return the latest labelled TPS and MSPT lines from a bounded log slice."""

    tps: TpsValues | None = None
    mspt: MsptValues | None = None
    for line in lines:
        parsed_tps = parse_paper_tps(line)
        if parsed_tps is not None:
            tps = parsed_tps
        parsed_mspt = parse_paper_mspt(line)
        if parsed_mspt is not None:
            mspt = parsed_mspt
    return tps, mspt


def performance_capable(distribution: str) -> bool:
    """Whether Blockstead has a known, bounded command source for a profile."""

    return distribution in PAPER_PERFORMANCE_DISTRIBUTIONS

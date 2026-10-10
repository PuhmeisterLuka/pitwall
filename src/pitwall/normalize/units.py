"""Parsers for the value formats the upstreams use."""

import re
from datetime import UTC, datetime

HEX_COLOUR = re.compile(r"[0-9A-Fa-f]{6}")


def clock_seconds(text: str) -> float:
    """'1:19:57.566', '1:46.653' or '59.1' -> seconds."""
    total = 0.0
    for part in text.split(":"):
        total = total * 60 + float(part)
    return round(total, 3)


def utc(text: str) -> datetime:
    """ISO 8601 timestamp -> aware UTC datetime (no offset means UTC)."""
    moment = datetime.fromisoformat(text)
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def hex_colour(value: str | None) -> str | None:
    """'27F4D2' -> '#27F4D2'; missing or malformed -> None."""
    if value and HEX_COLOUR.fullmatch(value):
        return f"#{value.upper()}"
    return None


def optional_int(value: str | None) -> int | None:
    """'6' -> 6; missing or not a number -> None."""
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None

"""Parsing of user-supplied dates and times (CLI and MCP)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, time, timedelta

from ohmypm.core.errors import ValidationError

_REL_RE = re.compile(r"^(\d+)\s*([mhdw])$")


def parse_when(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    """ISO date/datetime, ``today``/``yesterday`` or relative ``30m``/``12h``/``7d``/``2w``."""
    if value is None:
        return None
    text = value.strip().lower()
    now = datetime.now().astimezone()
    match = _REL_RE.match(text)
    if match:
        n, unit = int(match.group(1)), match.group(2)
        delta = {
            "m": timedelta(minutes=n),
            "h": timedelta(hours=n),
            "d": timedelta(days=n),
            "w": timedelta(weeks=n),
        }
        return (now - delta[unit]).astimezone(UTC)
    if text in ("today", "yesterday"):
        day = now.date() - timedelta(days=1 if text == "yesterday" else 0)
        moment = datetime.combine(day, time.max if end_of_day else time.min).astimezone()
        return moment.astimezone(UTC)
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
            day = datetime.fromisoformat(text).date()
            return datetime.combine(day, time.max if end_of_day else time.min).astimezone().astimezone(UTC)
        parsed = datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValidationError(
            f"Invalid date/time '{value}' (use 2026-11-04, 2026-11-04T10:00, today, 7d...)"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(UTC)

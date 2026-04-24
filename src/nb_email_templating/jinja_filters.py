"""Shared Jinja2 filters for email and dashboard templates."""

from datetime import date, datetime, timezone
from typing import Any

from jinja2 import Environment


def format_ts(value: Any) -> str:
    """Format a datetime or Unix epoch (seconds or milliseconds) as a UTC date/time string."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    if isinstance(value, date):
        return value.isoformat()
    try:
        n = float(value)
    except (TypeError, ValueError):
        return str(value)
    # NetBeez webhook timestamps are epoch milliseconds; treat large values as ms.
    if n > 1e12:
        n /= 1000.0
    try:
        dt = datetime.fromtimestamp(n, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return str(value)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def register_format_ts(env: Environment) -> None:
    env.filters["format_ts"] = format_ts

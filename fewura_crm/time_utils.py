from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


try:
    LOCAL_TIMEZONE = ZoneInfo("Europe/Paris")
except Exception:  # pragma: no cover - fallback for minimal Python installs
    LOCAL_TIMEZONE = datetime.now().astimezone().tzinfo or timezone.utc


def utc_now_sql() -> str:
    """Return the UTC-naive format used by SQLite CURRENT_TIMESTAMP."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def local_now() -> datetime:
    return datetime.now(LOCAL_TIMEZONE)


def local_input_to_utc_sql(value: str) -> str:
    """Convert an HTML datetime-local value to a UTC-naive SQLite value."""
    parsed = datetime.fromisoformat(value.strip())
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TIMEZONE)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def utc_sql_to_local_display(value: str | None) -> str:
    if not value:
        return ""
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(LOCAL_TIMEZONE).strftime("%d/%m/%Y %H:%M:%S")


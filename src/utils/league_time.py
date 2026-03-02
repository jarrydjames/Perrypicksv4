"""League-time utilities.

If you ever wondered how automation systems die: it's timezones.
So we centralize the definition of "today" for NBA scheduling.

We use America/Chicago as the operational league-day because it cleanly
covers most NBA scheduling behavior and matches existing assumptions in v5.

All functions return naive dates/strings suitable for DB keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.utils.datetime_utils import as_utc

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


LEAGUE_TZ_NAME = "America/Chicago"


def _tz() -> ZoneInfo:
    if ZoneInfo is None:
        raise RuntimeError("zoneinfo not available; upgrade python")
    return ZoneInfo(LEAGUE_TZ_NAME)


def league_now() -> datetime:
    """Current time in league timezone."""
    return datetime.now(tz=_tz())


def league_day_str(dt: datetime | None = None) -> str:
    """Return YYYY-MM-DD in league timezone."""
    d = (dt or league_now()).astimezone(_tz())
    return d.strftime("%Y-%m-%d")


def league_day_compact(dt: datetime | None = None) -> str:
    """Return YYYYMMDD in league timezone (ESPN scoreboard style)."""
    d = (dt or league_now()).astimezone(_tz())
    return d.strftime("%Y%m%d")


def league_day_start_utc(dt: datetime | None = None) -> datetime:
    """Start of current league day converted to UTC.

    Useful for DB queries like "today's games" in a timezone-stable way.
    """

    d = (dt or league_now()).astimezone(_tz())
    start_local = d.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_local.astimezone(ZoneInfo("UTC"))


def format_league_dt(dt: datetime, fmt: str = "%Y-%m-%d %I:%M %p %Z") -> str:
    """Format a datetime in league timezone.

    IMPORTANT:
    - This is intended for tz-aware datetimes or naive datetimes that are already UTC
      (like ESPN schedule ISO timestamps).
    - For DB `Game.game_date` (tz-naive league-local), use `format_league_local_dt()`.

    Example default: `2026-02-28 07:00 PM CST`
    """

    return as_league(dt).strftime(fmt)


def as_league_from_league_local(dt: datetime) -> datetime:
    """Convert a tz-naive *league-local* datetime to an aware league datetime."""

    from src.utils.datetime_utils import as_utc_from_league_local

    return as_utc_from_league_local(dt, league_tz_name=LEAGUE_TZ_NAME).astimezone(_tz())


def format_league_local_dt(dt: datetime, fmt: str = "%I:%M %p %Z") -> str:
    """Format a DB `Game.game_date` (naive league-local) in league timezone."""

    return as_league_from_league_local(dt).strftime(fmt)


def league_day_range_local_naive(day: str) -> tuple[datetime, datetime]:
    """Return (start,end) datetimes for a league day as tz-naive local values.

    This matches how `Game.game_date` is stored in SQLite.
    """

    start_local = datetime.fromisoformat(day).replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local.replace(hour=23, minute=59, second=59, microsecond=999999)
    return start_local, end_local


def as_league(dt: datetime) -> datetime:
    """Convert datetime to league timezone (America/Chicago)."""

    return as_utc(dt).astimezone(_tz())


__all__ = [
    "LEAGUE_TZ_NAME",
    "league_now",
    "league_day_str",
    "league_day_compact",
    "league_day_start_utc",
    "league_day_range_local_naive",
    "as_league",
    "as_league_from_league_local",
    "format_league_dt",
    "format_league_local_dt",
]

"""Datetime utilities.

SQLite + SQLAlchemy often produce tz-naive datetimes. If we call `.astimezone()`
against a naive datetime, Python may raise or assume local timezone.

To keep automation stable, we standardize:
- store + operate in UTC when possible
- when given a naive datetime, *assume it is UTC*

This matches how ESPN schedule times are parsed (+00:00) and how we use them.
"""

from __future__ import annotations

from datetime import datetime, timezone


def as_utc(dt: datetime) -> datetime:
    """Return a timezone-aware datetime in UTC.

    If dt is naive, we assume it already represents UTC.

    NOTE:
    - This is correct for schedule/feed datetimes (usually ISO w/ Z).
    - It is NOT correct for our DB Game.game_date values (stored as naive league-local).
      For those, use `as_utc_from_league_local()`.
    """

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def as_utc_from_league_local(dt: datetime, league_tz_name: str = "America/Chicago") -> datetime:
    """Convert a tz-naive *league-local* datetime into UTC.

    Our SQLite DB stores `Game.game_date` as tz-naive but representing league-local time.
    Treating it as UTC will shift displayed times and break 'started yet?' logic.
    """

    from zoneinfo import ZoneInfo

    if dt.tzinfo is None:
        dt_local = dt.replace(tzinfo=ZoneInfo(league_tz_name))
    else:
        dt_local = dt

    return dt_local.astimezone(timezone.utc)


__all__ = ["as_utc", "as_utc_from_league_local"]

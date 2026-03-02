from __future__ import annotations

"""Local-only market data access for the likelihood engine.

HARD RULE:
- This module must never call external odds providers.
- It calls the local composite Odds API client directly.

If local odds are unavailable, tracking should degrade gracefully (pause updates),
not silently fall back to paid providers.
"""

import logging
from dataclasses import dataclass

from src.odds.local_odds_client import OddsAPIError, OddsAPIMarketSnapshot, fetch_nba_odds_snapshot

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LocalOddsQuery:
    home: str
    away: str
    timeout_s: int = 10


def fetch_local_snapshot(q: LocalOddsQuery) -> OddsAPIMarketSnapshot:
    """Fetch a snapshot from the local composite odds API only."""

    try:
        return fetch_nba_odds_snapshot(
            home_name=q.home,
            away_name=q.away,
            timeout_s=q.timeout_s,
        )
    except OddsAPIError:
        raise
    except Exception as e:
        raise OddsAPIError(f"local odds snapshot failed: {e}") from e

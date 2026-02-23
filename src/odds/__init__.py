"""
Odds API Integration

Provides access to sportsbook odds via the-odds-api.com.
"""

from src.odds.odds_api import (
    OddsAPIMarketSnapshot,
    OddsAPIError,
    fetch_nba_odds_snapshot,
    get_api_key,
)

__all__ = [
    "OddsAPIMarketSnapshot",
    "OddsAPIError",
    "fetch_nba_odds_snapshot",
    "get_api_key",
]

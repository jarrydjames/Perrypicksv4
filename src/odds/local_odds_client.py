"""
PerryPicks Compatibility Client

Drop-in replacement for PerryPicks_v4's odds fetching.
Replace the-odds-api.com calls with this local API client.

Usage in PerryPicks:
    # Option 1: Set environment variable
    export ODDS_API_BASE_URL="http://localhost:8000"

    # Option 2: Modify PerryPicks to use this client
    from app.perrypicks_client import fetch_nba_odds_snapshot, OddsAPIMarketSnapshot

    # Then replace calls to odds_api.fetch_nba_odds_snapshot with this version
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

def _odds_api_base_url() -> str:
    # Default to localhost port 8890 (Odds_Api runs here, PerryPicks backend on 8000)
    return os.getenv("ODDS_API_BASE_URL", "http://localhost:8890")

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds between retries


@dataclass(frozen=True)
class OddsAPIMarketSnapshot:
    """
    Market snapshot matching PerryPicks_v4's OddsAPIMarketSnapshot.

    This is the exact same dataclass that PerryPicks expects from the-odds-api.
    """
    # Main markets (full game)
    total_points: Optional[float]
    total_over_odds: Optional[int]
    total_under_odds: Optional[int]

    spread_home: Optional[float]  # sportsbook convention: home line (e.g. -3.5)
    spread_home_odds: Optional[int]
    spread_away_odds: Optional[int]

    moneyline_home: Optional[int]
    moneyline_away: Optional[int]

    # Team totals (if supported by book/plan)
    team_total_home: Optional[float]
    team_total_home_over_odds: Optional[int]
    team_total_home_under_odds: Optional[int]

    team_total_away: Optional[float]
    team_total_away_over_odds: Optional[int]
    team_total_away_under_odds: Optional[int]

    # Derived team totals (calculated from spread + total)
    derived_team_total_home: Optional[float] = None
    derived_team_total_away: Optional[float] = None

    bookmaker: Optional[str] = None
    last_update: Optional[str] = None


class OddsAPIError(RuntimeError):
    """Error from the odds API."""
    pass


def fetch_nba_odds_snapshot(
    *,
    home_name: str,
    away_name: str,
    regions: str = "us",
    markets: str = "h2h,spreads,totals,team_totals",
    odds_format: str = "american",
    date_format: str = "iso",
    preferred_book: Optional[str] = None,
    timeout_s: int = 45,  # Increased from 10s - DraftKings Live takes ~30s
) -> OddsAPIMarketSnapshot:
    """
    Fetch a single consolidated odds snapshot for an NBA matchup.

    This is a drop-in replacement for PerryPicks_v4's fetch_nba_odds_snapshot.
    It calls the local Odds API instead of the-odds-api.com.

    Args:
        home_name: Home team name (e.g., "Boston Celtics", "BOS")
        away_name: Away team name (e.g., "Los Angeles Lakers", "LAL")
        regions: Region filter (ignored, for API compatibility)
        markets: Markets to fetch (ignored, all markets returned)
        odds_format: Odds format (ignored, always American)
        date_format: Date format (ignored, always ISO)
        preferred_book: Preferred bookmaker name
        timeout_s: Request timeout in seconds (default 45s for DraftKings Live)

    Returns:
        OddsAPIMarketSnapshot with odds data

    Raises:
        OddsAPIError: If the API call fails or no match found
    """
    url = f"{_odds_api_base_url()}/v1/snapshot"
    params = {
        "home_name": home_name,
        "away_name": away_name,
    }

    if preferred_book:
        params["preferred_book"] = preferred_book

    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            logger.info(f"Fetching odds snapshot (attempt {attempt + 1}/{MAX_RETRIES}): {away_name} @ {home_name}")
            response = requests.get(url, params=params, timeout=timeout_s)

            if response.status_code == 404:
                raise OddsAPIError(
                    f"No odds match found for {away_name} @ {home_name}"
                )

            response.raise_for_status()
            data = response.json()

            # Success - parse and return
            snapshot_data = data.get("snapshot", {})

            return OddsAPIMarketSnapshot(
                total_points=snapshot_data.get("total_points"),
                total_over_odds=snapshot_data.get("total_over_odds"),
                total_under_odds=snapshot_data.get("total_under_odds"),
                spread_home=snapshot_data.get("spread_home"),
                spread_home_odds=snapshot_data.get("spread_home_odds"),
                spread_away_odds=snapshot_data.get("spread_away_odds"),
                moneyline_home=snapshot_data.get("moneyline_home"),
                moneyline_away=snapshot_data.get("moneyline_away"),
                team_total_home=snapshot_data.get("team_total_home"),
                team_total_home_over_odds=snapshot_data.get("team_total_home_over_odds"),
                team_total_home_under_odds=snapshot_data.get("team_total_home_under_odds"),
                team_total_away=snapshot_data.get("team_total_away"),
                team_total_away_over_odds=snapshot_data.get("team_total_away_over_odds"),
                team_total_away_under_odds=snapshot_data.get("team_total_away_under_odds"),
                derived_team_total_home=snapshot_data.get("derived_team_total_home"),
                derived_team_total_away=snapshot_data.get("derived_team_total_away"),
                bookmaker=snapshot_data.get("bookmaker"),
                last_update=snapshot_data.get("last_update"),
            )

        except requests.exceptions.Timeout:
            last_error = f"Odds API timeout after {timeout_s}s"
            logger.warning(f"Timeout on attempt {attempt + 1}: {last_error}")
        except requests.exceptions.RequestException as e:
            last_error = f"Odds API request failed: {e}"
            logger.warning(f"Request error on attempt {attempt + 1}: {e}")
        except OddsAPIError:
            raise  # Don't retry on 404 - the game simply doesn't exist
        except Exception as e:
            last_error = f"Unexpected error: {e}"
            logger.warning(f"Unexpected error on attempt {attempt + 1}: {e}")

        # Wait before retry (except on last attempt)
        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_DELAY)

    # All retries failed
    raise OddsAPIError(f"Failed after {MAX_RETRIES} attempts: {last_error}")


def get_api_key() -> str:
    """
    Get API key (for compatibility with PerryPicks).

    This local API doesn't require an API key, so this always returns
    a placeholder. Included for drop-in compatibility.
    """
    return "local-api-no-key-required"


# ============================================================================
# Additional helper functions for schedule integration
# ============================================================================

def fetch_all_nba_odds(timeout_s: int = 10) -> Dict[str, Any]:
    """
    Fetch all available NBA odds.

    Returns:
        Dict with 'events' list containing all games with odds
    """
    url = f"{_odds_api_base_url()}/v1/odds"
    params = {"sport": "nba"}

    try:
        response = requests.get(url, params=params, timeout=timeout_s)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        raise OddsAPIError(f"Failed to fetch odds: {e}")


def health_check(timeout_s: int = 5) -> bool:
    """Check if the local odds API is healthy."""
    url = f"{_odds_api_base_url()}/v1/health"

    try:
        response = requests.get(url, timeout=timeout_s)
        return response.status_code == 200
    except Exception:
        return False


__all__ = [
    "OddsAPIMarketSnapshot",
    "OddsAPIError",
    "fetch_nba_odds_snapshot",
    "fetch_all_nba_odds",
    "health_check",
    "get_api_key",
]

"""
Temporal Feature Refresh Script

Updates the temporal feature store with recent completed games from NBA CDN.
This ensures rolling averages and team form features stay current.

Usage:
    python -m src.data.refresh_temporal
    python -m src.data.refresh_temporal --days 7
"""

import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

from src.data.game_data import fetch_box, fetch_pbp_df, first_half_score, behavior_counts_1h, get_efficiency_stats_from_box

logger = logging.getLogger(__name__)

# NBA CDN Endpoints
SCHEDULE_URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
BOX_URL = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"

# Headers for NBA CDN
NBA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
}

# Team tricode normalization
TEAM_TRICODE_MAP = {
    "NY": "NYK", "NO": "NOP", "SA": "SAS", "GS": "GSW",
    "PHO": "PHX", "UTAH": "UTA", "WSH": "WAS",
}


def fetch_season_schedule() -> List[dict]:
    """Fetch full season schedule from NBA CDN."""
    resp = requests.get(SCHEDULE_URL, headers=NBA_HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    games = []
    for game in data.get("leagueSchedule", {}).get("gameDates", []):
        for g in game.get("games", []):
            games.append({
                "game_id": g.get("gameId"),
                "game_date": g.get("gameDateEst", "")[:10],
                "home_team": g.get("homeTeam", {}).get("teamTricode"),
                "away_team": g.get("awayTeam", {}).get("teamTricode"),
                "game_status": g.get("gameStatus"),  # 1=scheduled, 2=live, 3=final
            })

    return games


def fetch_completed_games(since_date: str) -> List[dict]:
    """Fetch all completed games since a given date."""
    all_games = fetch_season_schedule()

    completed = []
    for g in all_games:
        if g["game_status"] == 3 and g["game_date"] >= since_date:
            completed.append(g)

    return completed


def extract_game_features(game_id: str) -> Optional[dict]:
    """Extract all features for a completed game."""
    try:
        # Fetch box score
        box = fetch_box(game_id)

        # Get basic info
        home = box.get("homeTeam", {})
        away = box.get("awayTeam", {})
        home_tri = home.get("teamTricode", "")
        away_tri = away.get("teamTricode", "")

        # Normalize tricodes
        home_tri = TEAM_TRICODE_MAP.get(home_tri, home_tri)
        away_tri = TEAM_TRICODE_MAP.get(away_tri, away_tri)

        # Get halftime scores
        h1_home, h1_away = first_half_score(box)
        if h1_home == 0 and h1_away == 0:
            logger.warning(f"No halftime scores for {game_id}")
            return None

        # Get efficiency stats
        eff = get_efficiency_stats_from_box(box)

        # Get final scores
        home_stats = home.get("statistics", {})
        away_stats = away.get("statistics", {})
        final_home = home_stats.get("points", 0)
        final_away = away_stats.get("points", 0)

        # Get behavior counts
        try:
            pbp = fetch_pbp_df(game_id)
            behavior = behavior_counts_1h(pbp)
        except Exception:
            behavior = {}

        # Calculate H2 scores
        h2_home = final_home - h1_home
        h2_away = final_away - h1_away
        h2_total = h2_home + h2_away
        h2_margin = h2_home - h2_away

        return {
            "game_id": game_id,
            "game_date": box.get("gameTimeUTC", "")[:10],
            "home_tri": home_tri,
            "away_tri": away_tri,
            "h1_home": h1_home,
            "h1_away": h1_away,
            "h1_total": h1_home + h1_away,
            "h1_margin": h1_home - h1_away,
            "h2_home": h2_home,
            "h2_away": h2_away,
            "h2_total": h2_total,
            "h2_margin": h2_margin,
            "final_home": final_home,
            "final_away": final_away,
            "final_total": final_home + final_away,
            "final_margin": final_home - final_away,
            # Efficiency stats
            **eff,
            # Behavior stats
            **{f"h1_{k}": v for k, v in behavior.items()},
        }

    except Exception as e:
        logger.error(f"Failed to extract features for {game_id}: {e}")
        return None


def calculate_rolling_features(df: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    """Calculate rolling average features for each team."""
    df = df.copy()
    df["game_date"] = pd.to_datetime(df["game_date"])

    # Sort by date
    df = df.sort_values("game_date")

    # For each team, calculate rolling stats
    team_features = {}

    for team in set(df["home_tri"].unique()) | set(df["away_tri"].unique()):
        team_games = df[(df["home_tri"] == team) | (df["away_tri"] == team)].copy()
        team_games = team_games.sort_values("game_date")

        # Calculate rolling averages
        for prefix, col in [("pts_scored", "final"), ("pts_allowed", "final")]:
            for side in ["home", "away"]:
                mask = team_games[f"{side}_tri"] == team
                if side == "home":
                    vals = team_games.loc[mask, f"final_home"]
                else:
                    vals = team_games.loc[mask, f"final_away"]

                # Rolling average
                rolling = vals.rolling(window=window, min_periods=1).mean()
                team_games.loc[mask, f"{side}_{prefix}_avg_{window}"] = rolling.values

        team_features[team] = team_games

    # Combine back
    result = pd.concat(team_features.values()).drop_duplicates(subset=["game_id"])
    return result.sort_values("game_date")


def refresh_temporal_store(days: int = 30) -> int:
    """
    Refresh the temporal feature store with recent games.

    Args:
        days: Number of days to look back for completed games

    Returns:
        Number of new games added
    """
    store_path = Path("data/processed/halftime_with_refined_temporal.parquet")

    # Load existing store
    if store_path.exists():
        existing_df = pd.read_parquet(store_path)
        existing_df["game_date"] = pd.to_datetime(existing_df["game_date"], errors="coerce", utc=True)
        existing_ids = set(existing_df["game_id"].tolist())
        latest_date = existing_df["game_date"].max().strftime("%Y-%m-%d")
        logger.info(f"Existing store has {len(existing_df)} games, latest: {latest_date}")
    else:
        existing_df = pd.DataFrame()
        existing_ids = set()
        latest_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    # Fetch completed games since latest date
    since_date = latest_date
    logger.info(f"Fetching completed games since {since_date}...")

    completed = fetch_completed_games(since_date)
    logger.info(f"Found {len(completed)} completed games since {since_date}")

    # Filter to new games only
    new_games = [g for g in completed if g["game_id"] not in existing_ids]
    logger.info(f"New games to process: {len(new_games)}")

    if not new_games:
        logger.info("No new games to add")
        return 0

    # Extract features for each new game
    new_rows = []
    for i, game in enumerate(new_games):
        logger.info(f"Processing {i+1}/{len(new_games)}: {game['away_team']} @ {game['home_team']}")
        features = extract_game_features(game["game_id"])
        if features:
            new_rows.append(features)

    if not new_rows:
        logger.warning("No features extracted from new games")
        return 0

    # Create new dataframe
    new_df = pd.DataFrame(new_rows)
    new_df["game_date"] = pd.to_datetime(new_df["game_date"], errors="coerce", utc=True)

    # Combine with existing
    combined = pd.concat([existing_df, new_df], ignore_index=True)
    combined = combined.sort_values("game_date").drop_duplicates(subset=["game_id"])

    # Recalculate rolling features
    logger.info("Recalculating rolling features...")
    combined = calculate_rolling_features(combined, window=5)

    # Save updated store
    combined.to_parquet(store_path, index=False)
    logger.info(f"Saved {len(combined)} games to {store_path}")

    return len(new_rows)


def main():
    parser = argparse.ArgumentParser(description="Refresh temporal feature store")
    parser.add_argument("--days", type=int, default=30, help="Days to look back")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    logger.info("=" * 60)
    logger.info("TEMPORAL FEATURE REFRESH")
    logger.info("=" * 60)

    added = refresh_temporal_store(days=args.days)

    logger.info("=" * 60)
    logger.info(f"COMPLETE: Added {added} new games")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()

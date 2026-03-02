"""
NBA Game Data Fetching from NBA CDN

Fetches box scores and play-by-play data from NBA.com CDN endpoints.
Includes caching and retry logic to handle rate limiting.

Endpoints:
- Box Score: https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json
- Play-by-Play: https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{gid}.json

Usage:
    from src.data.game_data import fetch_box, fetch_pbp_df, first_half_score

    game = fetch_box("0022500775")
    h1_home, h1_away = first_half_score(game)
"""

import re
import time
import logging
from pathlib import Path
from typing import Dict, Tuple, Optional
from datetime import datetime

import requests
import pandas as pd
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# NBA CDN Endpoints
CDN_BOX = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"
CDN_PBP = "https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{gid}.json"

# Connection pool with retry strategy for high concurrency
_session = requests.Session()
_retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 502, 503, 504],
)
_adapter = HTTPAdapter(
    max_retries=_retry_strategy,
    pool_connections=20,  # Increase from default 10 for concurrent games
    pool_maxsize=20,
)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)

# Cache settings
CACHE_DIR = Path(".cache/nba_cdn")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_TTL_SECONDS = 60  # 60 seconds - Rate limit protection: Increased to reduce NBA CDN requests

# Headers to avoid blocking (updated per NBA CDN best practices)
NBA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}


class GameDataError(Exception):
    """Raised when game data fetch fails."""
    pass


def extract_game_id(arg: str) -> str:
    """Extract game ID from URL or raw ID.

    Args:
        arg: Game ID or NBA.com URL

    Returns:
        Game ID string
    """
    m = re.search(r"(00\d{8,10})", arg)
    if not m:
        raise ValueError(f"Could not find a GAME_ID in: {arg}")
    return m.group(1)


def _get_cache_path(url: str) -> Path:
    """Get cache file path for a URL."""
    import hashlib
    url_hash = hashlib.md5(url.encode()).hexdigest()
    return CACHE_DIR / f"{url_hash}.json"


def _load_from_cache(cache_path: Path) -> Optional[dict]:
    """Load data from cache if not expired."""
    if not cache_path.exists():
        return None

    cache_age = time.time() - cache_path.stat().st_mtime
    if cache_age > CACHE_TTL_SECONDS:
        return None

    import json
    try:
        with open(cache_path, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError:
        # CRITICAL FIX: Delete corrupt cache file so it doesn't keep failing
        logger.warning(f"Corrupt cache file {cache_path}, deleting")
        cache_path.unlink(missing_ok=True)
        return None
    except Exception:
        return None


def _save_to_cache(cache_path: Path, data: dict) -> None:
    """Save data to cache."""
    import json
    try:
        with open(cache_path, 'w') as f:
            json.dump(data, f)
    except Exception:
        pass


def fetch_json(url: str, max_retries: int = 5) -> dict:
    """Fetch JSON from NBA.com CDN with retry logic and caching.

    Args:
        url: URL to fetch
        max_retries: Number of retries on 403/429 errors

    Returns:
        JSON response as dict

    Raises:
        requests.HTTPError: If all retries fail
    """
    # Check cache first
    cache_path = _get_cache_path(url)
    cached_data = _load_from_cache(cache_path)
    if cached_data is not None:
        logger.debug(f"Using cached data for {url}")
        return cached_data

    # Fetch with retry logic using connection pool
    for attempt in range(max_retries):
        try:
            r = _session.get(url, timeout=25, headers=NBA_HEADERS)
            r.raise_for_status()
            data = r.json()
            _save_to_cache(cache_path, data)
            return data
        except requests.HTTPError as e:
            if e.response.status_code in (403, 429) and attempt < max_retries - 1:
                wait_time = 2 ** (attempt + 1)
                logger.warning(f"NBA CDN returned {e.response.status_code}, retrying in {wait_time}s")
                time.sleep(wait_time)
                continue
            raise
        except (requests.Timeout, requests.ConnectionError, requests.SSLError) as e:
            # CRITICAL FIX: Handle timeout, connection, and SSL errors with retry
            if attempt < max_retries - 1:
                wait_time = 2 ** (attempt + 1)
                logger.warning(f"Network error ({type(e).__name__}) for {url}, retrying in {wait_time}s")
                time.sleep(wait_time)
                continue
            raise GameDataError(f"Network error after {max_retries} retries: {type(e).__name__}: {e}")

    raise GameDataError(f"Failed to fetch {url} after {max_retries} retries")


def fetch_box(gid: str) -> dict:
    """Fetch game box score from NBA CDN.

    Args:
        gid: Game ID

    Returns:
        Game data dict
    """
    url = CDN_BOX.format(gid=gid)
    logger.info(f"Fetching box score for game {gid}")
    data = fetch_json(url)

    # CRITICAL FIX: Validate response structure before accessing
    if "game" not in data:
        raise GameDataError(f"No 'game' key in response for {gid}. Response keys: {list(data.keys())}")

    return data["game"]


def fetch_pbp_df(gid: str) -> pd.DataFrame:
    """Fetch play-by-play data as DataFrame.

    Args:
        gid: Game ID

    Returns:
        DataFrame of play-by-play actions
    """
    url = CDN_PBP.format(gid=gid)
    logger.info(f"Fetching play-by-play for game {gid}")
    data = fetch_json(url)
    return pd.DataFrame(data["game"]["actions"])


def sum_first2(periods) -> int:
    """Sum scores from periods 1-2.

    Args:
        periods: List of period dicts

    Returns:
        Total points in first half
    """
    s = 0
    for p in (periods or []):
        if not isinstance(p, dict):
            continue
        try:
            period_num = int(float(p.get("period", 0)))
        except (ValueError, TypeError):
            period_num = 0
        if period_num in (1, 2):
            # CRITICAL FIX: Prefer period-specific keys over 'score' which might be cumulative
            for key in ("points", "pts", "periodScore", "score"):
                if key in p and p[key] is not None:
                    try:
                        val = float(p[key])
                        # Sanity check: period scores should rarely exceed 60
                        if val < 0 or val > 80:
                            logger.warning(f"Suspicious period score: {val} in period {period_num}, skipping")
                            continue
                        s += val
                    except (ValueError, TypeError):
                        pass
                    break
    return int(s)


def first_half_score(game: dict) -> Tuple[int, int]:
    """Extract first half scores from game data.

    Args:
        game: Game dict from fetch_box()

    Returns:
        Tuple of (home_score, away_score) for first half
    """
    home = game.get("homeTeam", {}) or {}
    away = game.get("awayTeam", {}) or {}
    return sum_first2(home.get("periods")), sum_first2(away.get("periods"))


def behavior_counts_1h(pbp: pd.DataFrame) -> dict:
    """Extract first half behavior counts from play-by-play.

    Args:
        pbp: Play-by-play DataFrame

    Returns:
        Dict with counts of 2pt, 3pt, turnovers, etc.
    """
    if pbp.empty:
        return {
            "h1_events": 0,
            "h1_n_2pt": 0,
            "h1_n_3pt": 0,
            "h1_n_turnover": 0,
            "h1_n_rebound": 0,
            "h1_n_foul": 0,
            "h1_n_timeout": 0,
            "h1_n_sub": 0,
        }

    fh = pbp[pbp["period"].astype(int) <= 2].copy()
    at = fh.get("actionType", pd.Series([""] * len(fh))).astype(str).fillna("")

    def count(prefix):
        return int(at.str.startswith(prefix).sum())

    return {
        "h1_events": int(len(fh)),
        "h1_n_2pt": count("2pt"),
        "h1_n_3pt": count("3pt"),
        "h1_n_turnover": count("turnover"),
        "h1_n_rebound": count("rebound"),
        "h1_n_foul": count("foul"),
        "h1_n_timeout": count("timeout"),
        "h1_n_sub": count("substitution"),
    }


def get_game_info(game: dict) -> dict:
    """Extract basic game info.

    Args:
        game: Game dict from fetch_box()

    Returns:
        Dict with game_id, teams, status, etc.
    """
    home = game.get("homeTeam", {}) or {}
    away = game.get("awayTeam", {}) or {}

    return {
        "game_id": game.get("gameId"),
        "game_status": game.get("gameStatus", 0),
        "game_time": game.get("gameTimeUTC", ""),
        "home_tricode": home.get("teamTricode", ""),
        "home_name": home.get("teamName", ""),
        "away_tricode": away.get("teamTricode", ""),
        "away_name": away.get("teamName", ""),
    }


def team_totals_from_box(team_data: dict) -> dict:
    """Extract team totals from box score team data.

    Args:
        team_data: homeTeam or awayTeam dict from box score

    Returns:
        Dict with team statistics
    """
    stats = team_data.get("statistics", {}) or {}

    return {
        "team_id": team_data.get("teamId", 0),
        "tricode": team_data.get("teamTricode", ""),
        "statistics": {
            "fieldGoalsMade": stats.get("fieldGoalsMade", 0),
            "fieldGoalsAttempted": stats.get("fieldGoalsAttempted", 0),
            "threePointersMade": stats.get("threePointersMade", 0),
            "threePointersAttempted": stats.get("threePointersAttempted", 0),
            "freeThrowsMade": stats.get("freeThrowsMade", 0),
            "freeThrowsAttempted": stats.get("freeThrowsAttempted", 0),
            "reboundsOffensive": stats.get("reboundsOffensive", 0),
            "reboundsDefensive": stats.get("reboundsDefensive", 0),
            "assists": stats.get("assists", 0),
            "turnovers": stats.get("turnovers", 0),
            "steals": stats.get("steals", 0),
            "blocks": stats.get("blocks", 0),
            "foulsPersonal": stats.get("foulsPersonal", 0),
            "points": stats.get("points", 0),
        },
    }


def calculate_efficiency_stats(prefix: str, team_stats: dict, opp_stats: dict) -> dict:
    """
    Calculate efficiency stats from box score statistics.

    These are the rate features expected by the REPTAR model:
    - efg: Effective field goal percentage (FGM + 0.5*3PM) / FGA
    - ftr: Free throw rate (FTA / FGA)
    - tpar: Three-point attempt rate (3PA / FGA)
    - tor: Turnover rate (TOV / possessions)
    - orbp: Offensive rebound percentage

    CRITICAL: All values are PROPORTIONS (0.52), not percentages (52.0)!

    Args:
        prefix: 'home' or 'away' for feature naming
        team_stats: Team statistics dict from team_totals_from_box()
        opp_stats: Opponent statistics dict

    Returns:
        Dict with efficiency stats
    """
    stats = team_stats.get("statistics", team_stats)

    # Extract raw stats
    fgm = stats.get("fieldGoalsMade", 0)
    fga = stats.get("fieldGoalsAttempted", 1)  # Default 1 to avoid div/0
    tpm = stats.get("threePointersMade", 0)
    tpa = stats.get("threePointersAttempted", 0)
    fta = stats.get("freeThrowsAttempted", 0)
    oreb = stats.get("reboundsOffensive", 0)
    tov = stats.get("turnovers", 1)  # Default 1 for ast_tov

    # Opponent rebounds for ORB%
    opp_stats_dict = opp_stats.get("statistics", opp_stats)
    dreb_opp = opp_stats_dict.get("reboundsDefensive", 0)

    # Calculate possessions (standard formula)
    poss = fga + 0.44 * fta + tov - oreb
    poss = max(poss, 1.0)

    # Calculate rates (all as PROPORTIONS, not percentages)
    efg = (fgm + 0.5 * tpm) / max(fga, 1)
    ftr = fta / max(fga, 1)
    tpar = tpa / max(fga, 1)
    tor = tov / poss
    orbp = oreb / max(oreb + dreb_opp, 1)

    return {
        f"{prefix}_efg": efg,
        f"{prefix}_ftr": ftr,
        f"{prefix}_tpar": tpar,
        f"{prefix}_tor": tor,
        f"{prefix}_orbp": orbp,
    }


def get_efficiency_stats_from_box(game: dict) -> dict:
    """
    Get efficiency stats for both teams from a box score.

    Args:
        game: Game dict from fetch_box()

    Returns:
        Dict with home_* and away_* efficiency stats
    """
    home_data = game.get("homeTeam", {}) or {}
    away_data = game.get("awayTeam", {}) or {}

    home_stats = team_totals_from_box(home_data)
    away_stats = team_totals_from_box(away_data)

    home_eff = calculate_efficiency_stats("home", home_stats, away_stats)
    away_eff = calculate_efficiency_stats("away", away_stats, home_stats)

    result = {}
    result.update(home_eff)
    result.update(away_eff)

    return result


def fetch_game_by_id(gid: str) -> Optional[dict]:
    """Fetch complete game data by ID.

    Args:
        gid: Game ID

    Returns:
        Game dict or None if not found
    """
    try:
        return fetch_box(gid)
    except Exception as e:
        logger.error(f"Failed to fetch game {gid}: {e}")
        return None


__all__ = [
    "fetch_box",
    "fetch_pbp_df",
    "fetch_json",
    "fetch_game_by_id",
    "extract_game_id",
    "first_half_score",
    "behavior_counts_1h",
    "sum_first2",
    "get_game_info",
    "team_totals_from_box",
    "calculate_efficiency_stats",
    "get_efficiency_stats_from_box",
    "GameDataError",
]

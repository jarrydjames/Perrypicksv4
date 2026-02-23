"""
NBA Schedule Fetching with ESPN + NBA CDN ID Mapping

This module fetches NBA game schedules and maps ESPN IDs to NBA.com IDs:

1. ESPN API - Fetches game schedule (no rate limiting)
2. NBA CDN - Provides full season schedule with NBA game IDs
3. Mapping - Matches games by team tricodes + game time

ESPN API Endpoint:
    https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={YYYYMMDD}

NBA CDN Schedule:
    https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json

Usage:
    from src.schedule import fetch_schedule, main_with_output

    # Get schedule with NBA IDs
    result = main_with_output('2026-02-11')
    for game in result['games']:
        print(f"{game['away_team']} @ {game['home_team']} - NBA ID: {game['nba_id']}")
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import requests
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# TEAM ABBREVIATION NORMALIZATION
# ============================================================================

# ESPN sometimes uses different abbreviations than NBA.com
TEAM_ABBR_NORMALIZATION = {
    # Atlanta Hawks
    'ATL': 'ATL',
    # Boston Celtics
    'BOS': 'BOS', 'BOSTON': 'BOS',
    # Brooklyn Nets
    'BKN': 'BKN', 'BROOKLYN': 'BKN',
    # Charlotte Hornets
    'CHA': 'CHA', 'CHARLOTTE': 'CHA',
    # Chicago Bulls
    'CHI': 'CHI', 'CHICAGO': 'CHI',
    # Cleveland Cavaliers
    'CLE': 'CLE', 'CLEVELAND': 'CLE', 'CAVS': 'CLE',
    # Dallas Mavericks
    'DAL': 'DAL', 'DALLAS': 'DAL',
    # Denver Nuggets
    'DEN': 'DEN', 'DENVER': 'DEN',
    # Detroit Pistons
    'DET': 'DET', 'DETROIT': 'DET',
    # Golden State Warriors
    'GSW': 'GSW', 'GS': 'GSW', 'GOLDEN STATE': 'GSW', 'WARRIORS': 'GSW',
    # Houston Rockets
    'HOU': 'HOU', 'HOUSTON': 'HOU',
    # Indiana Pacers
    'IND': 'IND', 'INDIANA': 'IND',
    # Los Angeles Clippers
    'LAC': 'LAC', 'LA CLIPPERS': 'LAC', 'CLIPPERS': 'LAC',
    # Los Angeles Lakers
    'LAL': 'LAL', 'LA LAKERS': 'LAL', 'LAKERS': 'LAL',
    # Memphis Grizzlies
    'MEM': 'MEM', 'MEMPHIS': 'MEM',
    # Miami Heat
    'MIA': 'MIA', 'MIAMI': 'MIA',
    # Milwaukee Bucks
    'MIL': 'MIL', 'MILWAUKEE': 'MIL',
    # Minnesota Timberwolves
    'MIN': 'MIN', 'MINNESOTA': 'MIN',
    # New Orleans Pelicans
    'NOP': 'NOP', 'NO': 'NOP', 'NEW ORLEANS': 'NOP', 'PELICANS': 'NOP',
    # New York Knicks
    'NYK': 'NYK', 'NY': 'NYK', 'NEW YORK': 'NYK', 'KNICKS': 'NYK',
    # Oklahoma City Thunder
    'OKC': 'OKC', 'OKLAHOMA CITY': 'OKC', 'THUNDER': 'OKC',
    # Orlando Magic
    'ORL': 'ORL', 'ORLANDO': 'ORL',
    # Philadelphia 76ers
    'PHI': 'PHI', 'PHILADELPHIA': 'PHI', '76ERS': 'PHI',
    # Phoenix Suns
    'PHX': 'PHX', 'PHO': 'PHX', 'PHOENIX': 'PHX', 'SUNS': 'PHX',
    # Portland Trail Blazers
    'POR': 'POR', 'PORTLAND': 'POR', 'TRAIL BLAZERS': 'POR', 'BLAZERS': 'POR',
    # Sacramento Kings
    'SAC': 'SAC', 'SACRAMENTO': 'SAC', 'KINGS': 'SAC',
    # San Antonio Spurs
    'SAS': 'SAS', 'SA': 'SAS', 'SAN ANTONIO': 'SAS', 'SPURS': 'SAS',
    # Toronto Raptors
    'TOR': 'TOR', 'TORONTO': 'TOR', 'RAPTORS': 'TOR',
    # Utah Jazz
    'UTA': 'UTA', 'UTAH': 'UTA', 'JAZZ': 'UTA',
    # Washington Wizards
    'WAS': 'WAS', 'WSH': 'WAS', 'WASHINGTON': 'WAS', 'WIZARDS': 'WAS',
}

# Add self-mappings for already-normalized values
TEAM_ABBR_NORMALIZATION.update({v: v for v in [
    'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET',
    'GSW', 'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN',
    'NOP', 'NYK', 'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS',
    'TOR', 'UTA', 'WAS'
]})


def normalize_team_abbr(team_abbr: str) -> str:
    """Normalize team abbreviation to NBA.com format."""
    if not team_abbr:
        return ''
    return TEAM_ABBR_NORMALIZATION.get(team_abbr.upper(), team_abbr.upper())


# ============================================================================
# API FETCHING
# ============================================================================

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


def fetch_espn_schedule(date_str: str, timeout: int = 10) -> Dict:
    """
    Fetch game schedule from ESPN API.

    Args:
        date_str: Date in YYYY-MM-DD format
        timeout: Request timeout in seconds

    Returns:
        ESPN API response data
    """
    date_formatted = date_str.replace('-', '')
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={date_formatted}"

    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=timeout)
        if response.status_code == 200:
            logger.info(f"Fetched ESPN schedule for {date_str}")
            return response.json()
    except Exception as e:
        logger.warning(f"Error fetching ESPN schedule: {e}")

    return {}


def fetch_nba_cdn_schedule(timeout: int = 10) -> Dict:
    """
    Fetch full season schedule from NBA CDN (no rate limiting).

    Uses scheduleLeagueV2.json which includes NBA game IDs.

    Returns:
        Full season schedule data
    """
    url = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"

    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=timeout)
        if response.status_code == 200:
            logger.info("Fetched NBA CDN full season schedule")
            return response.json()
    except Exception as e:
        logger.warning(f"Error fetching NBA CDN schedule: {e}")

    return {}


# ============================================================================
# SCHEDULE EXTRACTION
# ============================================================================

def extract_nba_games_for_date(nba_data: Dict, date_str: str) -> List[Dict]:
    """
    Extract NBA games for a specific date from CDN schedule.

    Args:
        nba_data: Full NBA CDN schedule data
        date_str: Date in YYYY-MM-DD format

    Returns:
        List of games with NBA IDs for the specified date
    """
    games = []

    if 'leagueSchedule' not in nba_data:
        return games

    game_dates = nba_data['leagueSchedule'].get('gameDates', [])

    # Format target date (NBA CDN uses MM/DD/YYYY format)
    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d')
        target_date_str_1 = target_date.strftime('%m/%d/%Y')
        target_date_str_2 = target_date.strftime('%Y-%m-%d')
    except ValueError:
        return games

    # Find matching date
    for date_entry in game_dates:
        entry_date = date_entry.get('gameDate', '')

        # Match date in either format
        if target_date_str_1 in str(entry_date) or target_date_str_2 in str(entry_date):
            for game in date_entry.get('games', []):
                game_id = game.get('gameId')
                away_team = normalize_team_abbr(game.get('awayTeam', {}).get('teamTricode', ''))
                home_team = normalize_team_abbr(game.get('homeTeam', {}).get('teamTricode', ''))
                game_time_utc = game.get('gameDateTimeUTC', game.get('gameDateUTC', ''))

                games.append({
                    'game_id': game_id,
                    'away_team': away_team,
                    'home_team': home_team,
                    'game_time_utc': game_time_utc
                })
            break

    return games


def create_espn_to_nba_mapping(espn_data: Dict, nba_games: List[Dict]) -> Dict[str, Optional[str]]:
    """
    Map ESPN game IDs to NBA.com game IDs by matching games.

    Matches by:
    1. Away team tricode (normalized)
    2. Home team tricode (normalized)
    3. Game time (UTC) - for disambiguation

    Args:
        espn_data: ESPN API response data
        nba_games: List of NBA games for the same date

    Returns:
        Dict mapping ESPN game IDs to NBA game IDs
    """
    mapping = {}

    if 'events' not in espn_data:
        return mapping

    espn_games = espn_data['events']

    # Create lookup for NBA games
    nba_lookup = {}
    for nba_game in nba_games:
        away_tri = normalize_team_abbr(nba_game.get('away_team', ''))
        home_tri = normalize_team_abbr(nba_game.get('home_team', ''))

        key = f"{away_tri}|{home_tri}"

        if key not in nba_lookup:
            nba_lookup[key] = []
        nba_lookup[key].append(nba_game)

    # Map ESPN games to NBA games
    for espn_game in espn_games:
        espn_id = espn_game.get('id')

        competitors = espn_game.get('competitions', [{}])[0].get('competitors', [])

        if len(competitors) < 2:
            mapping[espn_id] = None
            continue

        # Determine home/away
        if competitors[0].get('homeAway') == 'home':
            home_tri = competitors[0].get('team', {}).get('abbreviation', '')
            away_tri = competitors[1].get('team', {}).get('abbreviation', '')
        else:
            home_tri = competitors[1].get('team', {}).get('abbreviation', '')
            away_tri = competitors[0].get('team', {}).get('abbreviation', '')

        # Normalize and find match
        away_tri_norm = normalize_team_abbr(away_tri)
        home_tri_norm = normalize_team_abbr(home_tri)

        key = f"{away_tri_norm}|{home_tri_norm}"

        if key in nba_lookup:
            nba_match = nba_lookup[key][0]
            nba_id = nba_match.get('game_id')
            mapping[espn_id] = nba_id

            # Remove from lookup to prevent duplicate mappings
            if len(nba_lookup[key]) > 1:
                nba_lookup[key].pop(0)
            else:
                del nba_lookup[key]
        else:
            mapping[espn_id] = None

    return mapping


# ============================================================================
# MAIN API
# ============================================================================

def fetch_schedule(date_str: str) -> Dict:
    """
    Fetch game schedule with NBA IDs for a specific date.

    Args:
        date_str: Date in YYYY-MM-DD format

    Returns:
        Dict with:
            - 'date': Date string
            - 'mapping': ESPN ID to NBA ID mapping
            - 'games': List of game dicts
    """
    # Fetch schedules
    espn_data = fetch_espn_schedule(date_str)
    nba_data = fetch_nba_cdn_schedule()

    # Extract NBA games for target date
    nba_games = extract_nba_games_for_date(nba_data, date_str)

    # Create mapping
    mapping = create_espn_to_nba_mapping(espn_data, nba_games)

    # Build games list
    games = []

    if 'events' in espn_data:
        for game in espn_data['events']:
            espn_id = game.get('id')
            nba_id = mapping.get(espn_id)

            competitors = game.get('competitions', [{}])[0].get('competitors', [])

            if len(competitors) >= 2:
                if competitors[0].get('homeAway') == 'home':
                    home_team = normalize_team_abbr(competitors[0].get('team', {}).get('abbreviation', ''))
                    away_team = normalize_team_abbr(competitors[1].get('team', {}).get('abbreviation', ''))
                else:
                    home_team = normalize_team_abbr(competitors[1].get('team', {}).get('abbreviation', ''))
                    away_team = normalize_team_abbr(competitors[0].get('team', {}).get('abbreviation', ''))
            else:
                home_team = ''
                away_team = ''

            status = game.get('status', {}).get('type', {}).get('name', 'Unknown')
            date_time = game.get('date', '')

            games.append({
                'espn_id': espn_id,
                'nba_id': nba_id,
                'away_team': away_team,
                'home_team': home_team,
                'status': status,
                'date_time': date_time
            })

    return {
        'date': date_str,
        'mapping': mapping,
        'games': games
    }


# Alias for compatibility
main_with_output = fetch_schedule


def get_nba_ids(date_str: str) -> List[str]:
    """
    Get list of NBA.com game IDs for a date.

    Args:
        date_str: Date in YYYY-MM-DD format

    Returns:
        List of NBA game IDs (excludes unmapped games)
    """
    result = fetch_schedule(date_str)
    return [g['nba_id'] for g in result['games'] if g['nba_id']]


def print_schedule(date_str: str) -> None:
    """Print formatted schedule for a date."""
    result = fetch_schedule(date_str)
    games = result['games']

    print("=" * 90)
    print(f"NBA SCHEDULE FOR {date_str}")
    print("=" * 90)

    if not games:
        print("No games found.")
        return

    mapped = sum(1 for g in games if g['nba_id'])
    print(f"Games: {len(games)} | Mapped: {mapped} | Unmapped: {len(games) - mapped}")
    print()
    print(f"{'ESPN ID':<12} | {'NBA ID':<15} | {'Matchup':<15} | {'Status'}")
    print("-" * 90)

    for g in games:
        nba_display = g['nba_id'] or 'NOT MAPPED'
        matchup = f"{g['away_team']} @ {g['home_team']}"
        print(f"{g['espn_id']:<12} | {nba_display:<15} | {matchup:<15} | {g['status']}")

    print("=" * 90)


__all__ = [
    "fetch_schedule",
    "main_with_output",
    "get_nba_ids",
    "print_schedule",
    "fetch_espn_schedule",
    "fetch_nba_cdn_schedule",
    "normalize_team_abbr",
]

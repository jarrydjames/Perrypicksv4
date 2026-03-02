"""
Game State Monitoring for PerryPicks

Monitors live NBA games by polling NBA CDN endpoints and detecting
game state changes for trigger evaluation.

Usage:
    from src.automation.game_state import GameStateMonitor

    monitor = GameStateMonitor()
    monitor.add_game("0022500775")
    states = monitor.update_all_games()
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set
from src.data.game_data import fetch_box, get_game_info
import requests

logger = logging.getLogger(__name__)


@dataclass
class GameState:
    """Represents the current state of an NBA game."""

    game_id: str
    status: str = "unknown"  # scheduled, live, halftime, final
    period: int = 0
    time_remaining: str = "12:00"
    home_score: int = 0
    away_score: int = 0
    home_team: str = ""
    away_team: str = ""
    home_tricode: str = ""
    away_tricode: str = ""
    game_time_utc: str = ""
    last_updated: datetime = field(default_factory=datetime.utcnow)

    @property
    def is_live(self) -> bool:
        """Check if game is currently live."""
        return self.status == "live"

    @property
    def is_halftime(self) -> bool:
        """Check if game is at halftime."""
        return self.status == "halftime"

    @property
    def is_final(self) -> bool:
        """Check if game is finished."""
        return self.status == "final"

    @property
    def is_scheduled(self) -> bool:
        """Check if game hasn't started yet."""
        return self.status == "scheduled"

    @property
    def total_score(self) -> int:
        """Get total combined score."""
        return self.home_score + self.away_score

    @property
    def margin(self) -> int:
        """Get current margin (positive = home leading)."""
        return self.home_score - self.away_score

    @property
    def minutes_remaining_in_period(self) -> int:
        """Get minutes remaining in current period."""
        try:
            parts = self.time_remaining.split(":")
            return int(parts[0])
        except (ValueError, IndexError):
            return 12

    @property
    def display_name(self) -> str:
        """Get display name for the game."""
        return f"{self.away_tricode} @ {self.home_tricode}"

    def __repr__(self) -> str:
        return (
            f"GameState({self.game_id}, {self.status}, "
            f"Q{self.period} {self.time_remaining}, "
            f"{self.away_score}-{self.home_score})"
        )


class GameStateMonitor:
    """
    Monitors live NBA games by polling NBA CDN.

    This class maintains a registry of games to monitor and provides
    efficient updates for all tracked games.
    """

    # Polling interval in seconds
    DEFAULT_POLL_INTERVAL = 45  # Increased to reduce NBA CDN requests and prevent rate limiting
    
    def __init__(self, poll_interval: int = None):
        self.poll_interval = poll_interval or self.DEFAULT_POLL_INTERVAL
        self._games: Dict[str, GameState] = {}
        self._last_poll: Dict[str, float] = {}
        self._monitored_games: Set[str] = set()
        self._espn_game_cache: Dict[str, dict] = {}  # Cache ESPN game data

    def add_game(self, game_id: str) -> None:
        """Add a game to monitor."""
        if game_id not in self._monitored_games:
            self._monitored_games.add(game_id)
            logger.info(f"Added game {game_id} to monitoring")

    def remove_game(self, game_id: str) -> None:
        """Remove a game from monitoring."""
        self._monitored_games.discard(game_id)
        if game_id in self._games:
            del self._games[game_id]
        logger.info(f"Removed game {game_id} from monitoring")

    def get_game_state(self, game_id: str) -> Optional[GameState]:
        """Get current state for a game."""
        return self._games.get(game_id)

    def get_all_states(self) -> Dict[str, GameState]:
        """Get all tracked game states."""
        return self._games.copy()

    def _fetch_espn_status(self, game_id: str) -> Optional[dict]:
        """
        Fetch game status from ESPN API (fallback for NBA CDN rate limits).
        
        ESPN API is more lenient with rate limits and provides:
        - Game status (scheduled, live, halftime, final)
        - Current period and time remaining
        - Scores
        """
        try:
            # Fetch today's scoreboard from ESPN
            from datetime import datetime
            today = datetime.now().strftime("%Y%m%d")
            url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={today}"
            
            resp = requests.get(url, timeout=10)
            data = resp.json()
            events = data.get("events", [])
            
            for event in events:
                event_id = event.get("id")
                
                # Match by game ID (ESPN uses different ID format, need to match by teams)
                if event_id == game_id:
                    return event
                
                # Also try to match by looking up in database to find ESPN event ID
                # For now, cache all events and return the one that matches our game
                self._espn_game_cache[event_id] = event
            
            # If we cached all events, try to find a match
            # This is a temporary fix - ideally we'd have a mapping
            if self._espn_game_cache:
                return self._espn_game_cache.get(game_id)
            
            return None
            
        except Exception as e:
            logger.warning(f"ESPN API fetch failed for {game_id}: {e}")
            return None
    
    def _parse_espn_status(self, game_id: str, espn_data: dict) -> Optional[GameState]:
        """
        Parse ESPN API response into GameState object.
        
        ESPN provides game status without requiring box score data.
        """
        try:
            status = espn_data.get("status", {})
            status_type = status.get("type", {})
            status_desc = status_type.get("description", "")
            
            competitions = espn_data.get("competitions", [])
            if not competitions:
                return None
            
            comp = competitions[0]
            home_team = comp["competitors"][0]
            away_team = comp["competitors"][1]
            
            # Get scores
            home_score = home_team.get("score", 0) or 0
            away_score = away_team.get("score", 0) or 0
            
            # Get period and time
            period = status.get("period", 0) or 0
            time_remaining = status.get("displayClock", "12:00") or "12:00"
            
            # Determine status
            if status_desc == "Final":
                game_status = "final"
            elif "halftime" in status_desc.lower():
                game_status = "halftime"
            elif period > 0:
                game_status = "live"
            else:
                game_status = "scheduled"
            
            # Get team info
            home_tricode = home_team.get("team", {}).get("abbreviation", "")
            away_tricode = away_team.get("team", {}).get("abbreviation", "")
            home_name = home_team.get("team", {}).get("displayName", "")
            away_name = away_team.get("team", {}).get("displayName", "")
            
            return GameState(
                game_id=game_id,
                status=game_status,
                period=period,
                time_remaining=time_remaining,
                home_score=int(home_score),
                away_score=int(away_score),
                home_team=home_name,
                away_team=away_name,
                home_tricode=home_tricode,
                away_tricode=away_tricode,
                game_time_utc="",
                last_updated=datetime.now(),
            )
            
        except Exception as e:
            logger.error(f"Failed to parse ESPN status for {game_id}: {e}")
            return None

    def update_game(self, game_id: str) -> Optional[GameState]:
        """
        Update state for a single game.
        
        Tries NBA CDN first, falls back to ESPN API on 403 errors.

        Returns:
            Updated GameState or None if fetch failed
        """
        try:
            box = fetch_box(game_id)
            state = self._parse_box_score(game_id, box)
            self._games[game_id] = state
            self._last_poll[game_id] = time.time()
            return state
        except Exception as e:
            error_str = str(e).lower()
            
            # Check if it's a 403 rate limit error
            if '403' in error_str or 'forbidden' in error_str:
                logger.warning(f"NBA CDN rate limited for {game_id}, falling back to ESPN API")
                
                # Try ESPN API as fallback
                espn_data = self._fetch_espn_status(game_id)
                if espn_data:
                    state = self._parse_espn_status(game_id, espn_data)
                    if state:
                        self._games[game_id] = state
                        self._last_poll[game_id] = time.time()
                        return state
                
                logger.error(f"Both NBA CDN and ESPN API failed for {game_id}")
                return None
            else:
                logger.error(f"Failed to update game {game_id}: {e}")
                return None

    def update_all_games(self) -> List[GameState]:
        """
        Update all monitored games.

        Returns:
            List of updated game states
        """
        updated = []
        for game_id in list(self._monitored_games):
            state = self.update_game(game_id)
            if state:
                updated.append(state)
        return updated

    def _parse_box_score(self, game_id: str, box: dict) -> GameState:
        """Parse NBA CDN box score into GameState."""
        home_team = box.get("homeTeam", {}) or {}
        away_team = box.get("awayTeam", {}) or {}

        # Get scores
        home_score = home_team.get("score", 0) or 0
        away_score = away_team.get("score", 0) or 0

        # Get period and time
        period = box.get("period", 0) or 0
        game_status = box.get("gameStatus", 0) or 0

        # Parse time remaining
        time_remaining = box.get("gameClock", "12:00") or "12:00"

        # Determine status
        status = self._determine_status(game_status, period, time_remaining, box)

        # Get team info
        home_tricode = home_team.get("teamTricode", "")
        away_tricode = away_team.get("teamTricode", "")

        return GameState(
            game_id=game_id,
            status=status,
            period=period,
            time_remaining=time_remaining,
            home_score=int(home_score),
            away_score=int(away_score),
            home_team=home_team.get("teamName", ""),
            away_team=away_team.get("teamName", ""),
            home_tricode=home_tricode,
            away_tricode=away_tricode,
            game_time_utc=box.get("gameTimeUTC", ""),
            last_updated=datetime.utcnow(),
        )

    def _determine_status(
        self, game_status: int, period: int, time_remaining: str, box: dict
    ) -> str:
        """Determine game status from box score data."""
        # Game status codes from NBA CDN:
        # 1 = scheduled
        # 2 = live
        # 3 = final

        if game_status == 1:
            return "scheduled"

        if game_status == 3:
            return "final"

        if game_status == 2:
            # Check for halftime
            if self._is_halftime(period, time_remaining, box):
                return "halftime"
            return "live"

        return "unknown"

    def _is_halftime(self, period: int, time_remaining: str, box: dict) -> bool:
        """Detect if game is at halftime."""
        # Halftime conditions:
        # 1. Period is 2 (end of Q2)
        # 2. Time remaining is 00:00 or 0.0 (various formats)
        # 3. Both teams have completed 2 periods

        # Handle multiple clock formats: "00:00", "0:00", "0.0"
        time_remaining_zero = (
            time_remaining == "00:00" or 
            time_remaining == "0:00" or 
            time_remaining == "0.0"
        )

        if not time_remaining_zero:
            return False

        if period != 2:
            return False

        # Check period counts
        home_team = box.get("homeTeam", {}) or {}
        away_team = box.get("awayTeam", {}) or {}

        home_periods = len(home_team.get("periods", []) or [])
        away_periods = len(away_team.get("periods", []) or [])

        return home_periods >= 2 and away_periods >= 2

    def is_halftime(self, game_id: str) -> bool:
        """Check if a specific game is at halftime."""
        state = self.get_game_state(game_id)
        return state.is_halftime if state else False

    def is_q3_trigger(self, game_id: str) -> bool:
        """Check if game is in Q3 with 5 minutes or less remaining."""
        state = self.get_game_state(game_id)
        if not state:
            return False

        return (
            state.period == 3
            and state.is_live
            and state.minutes_remaining_in_period <= 5
        )

    def is_game_final(self, game_id: str) -> bool:
        """Check if a game has finished."""
        state = self.get_game_state(game_id)
        return state.is_final if state else False

    def get_live_games(self) -> List[GameState]:
        """Get all currently live games."""
        return [s for s in self._games.values() if s.is_live]

    def get_halftime_games(self) -> List[GameState]:
        """Get all games currently at halftime."""
        return [s for s in self._games.values() if s.is_halftime]

    def get_final_games(self) -> List[GameState]:
        """Get all finished games."""
        return [s for s in self._games.values() if s.is_final]


__all__ = ["GameState", "GameStateMonitor"]

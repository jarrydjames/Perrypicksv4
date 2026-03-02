"""
Automation Service for PerryPicks

Main service that coordinates game monitoring, trigger detection,
prediction generation, and Discord posting.

Usage:
    from src.automation import AutomationService

    service = AutomationService(
        discord_webhook_url="https://discord.com/api/webhooks/...",
        platforms=["discord"],
    )
    service.start()
"""

import logging
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Set

from src.automation.game_state import GameState, GameStateMonitor
from src.automation.triggers import TriggerEngine, TriggerEvent, TriggerType
from src.automation.post_generator import PostGenerator, BettingRecommendation
from src.automation.discord_client import DiscordClient, DiscordPostResult
from src.schedule import fetch_schedule

logger = logging.getLogger(__name__)


@dataclass
class ServiceStats:
    """Statistics for the automation service."""

    games_monitored: int = 0
    triggers_fired: int = 0
    posts_successful: int = 0
    posts_failed: int = 0
    last_poll_time: Optional[datetime] = None
    uptime_seconds: float = 0.0
    started_at: Optional[datetime] = None


class AutomationService:
    """
    Main automation service that coordinates all components.

    This service:
    1. Fetches daily schedule and adds games to monitoring
    2. Polls games for state changes
    3. Detects triggers (halftime, Q3)
    4. Generates predictions
    5. Posts to Discord
    """

    # Default polling interval (30 seconds)
    DEFAULT_POLL_INTERVAL = 30

    # Schedule refresh interval (5 minutes)
    SCHEDULE_REFRESH_INTERVAL = 300

    def __init__(
        self,
        discord_webhook_url: Optional[str] = None,
        prediction_callback: Optional[Callable] = None,
        poll_interval: int = None,
        platforms: List[str] = None,
        include_betting: bool = True,
    ):
        """
        Initialize automation service.

        Args:
            discord_webhook_url: Discord webhook URL for posting
            prediction_callback: Function to generate predictions
                Signature: (game_id: str, trigger_type: TriggerType, state: GameState) -> Optional[dict]
            poll_interval: Polling interval in seconds
            platforms: List of platforms to post to (default: ["discord"])
            include_betting: Whether to include betting recommendations
        """
        self.poll_interval = poll_interval or self.DEFAULT_POLL_INTERVAL
        self.platforms = platforms or ["discord"]
        self.include_betting = include_betting
        self.prediction_callback = prediction_callback

        # Components
        self.game_monitor = GameStateMonitor(poll_interval=self.poll_interval)
        self.trigger_engine = TriggerEngine()
        self.post_generator = PostGenerator(include_betting=include_betting)

        # Discord client
        self.discord: Optional[DiscordClient] = None
        if discord_webhook_url:
            self.discord = DiscordClient(discord_webhook_url)

        # State
        self._running = False
        self._current_date: Optional[str] = None
        self._schedule_refreshed: Optional[datetime] = None
        self._stats = ServiceStats()

        # Signal handlers
        self._setup_signal_handlers()

    def _setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown."""
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    def _handle_shutdown(self, signum, frame) -> None:
        """Handle shutdown signal - set flag only (safe in signal context)."""
        self._running = False

    @property
    def stats(self) -> ServiceStats:
        """Get current service statistics."""
        if self._stats.started_at:
            self._stats.uptime_seconds = (datetime.now() - self._stats.started_at).total_seconds()
        return self._stats

    def start(self) -> None:
        """Start the automation service."""
        logger.info("Starting PerryPicks Automation Service")
        self._running = True
        self._stats.started_at = datetime.now()

        try:
            self._main_loop()
        except Exception as e:
            logger.error(f"Service error: {e}")
            raise
        finally:
            self._cleanup()

    def stop(self) -> None:
        """Stop the automation service."""
        logger.info("Stopping PerryPicks Automation Service")
        self._running = False

    def _main_loop(self) -> None:
        """Main service loop."""
        while self._running:
            try:
                # Get current date (use local time, not UTC, to avoid day roll issues)
                current_date = datetime.now().strftime("%Y-%m-%d")

                # Refresh schedule if needed
                if self._should_refresh_schedule(current_date):
                    self._refresh_schedule(current_date)

                # Update all monitored games
                updated_states = self.game_monitor.update_all_games()
                self._stats.last_poll_time = datetime.now()
                logger.debug(f"Updated {len(updated_states)} games")

                # Evaluate triggers and get events
                events = self.trigger_engine.evaluate_all(
                    self.game_monitor,
                    prediction_callback=self.prediction_callback,
                )

                # Process events
                for event in events:
                    self._stats.triggers_fired += 1
                    self._process_event(event)

                # Clean up posted events
                self.trigger_engine.clear_posted_events()

                # Clean up finished games to prevent memory leaks
                finished_games = {
                    gid for gid in list(self.game_monitor._monitored_games)
                    if self.game_monitor.is_game_final(gid)
                }
                if finished_games:
                    self.trigger_engine.cleanup_finished_games(finished_games)
                    logger.debug(f"Cleaned up {len(finished_games)} finished games")

                # Sleep until next poll
                time.sleep(self.poll_interval)

            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(self.poll_interval)

    def _should_refresh_schedule(self, current_date: str) -> bool:
        """Check if schedule should be refreshed."""
        # New day
        if self._current_date != current_date:
            return True

        # Time since last refresh
        if self._schedule_refreshed:
            elapsed = (datetime.now() - self._schedule_refreshed).total_seconds()
            if elapsed > self.SCHEDULE_REFRESH_INTERVAL:
                return True

        return self._current_date is None

    def _refresh_schedule(self, date_str: str) -> None:
        """Refresh game schedule for a date."""
        logger.info(f"Refreshing schedule for {date_str}")

        try:
            result = fetch_schedule(date_str)
            games = result.get("games", [])

            # Add games with NBA IDs to monitoring
            added = 0
            for game in games:
                nba_id = game.get("nba_id")
                if nba_id:
                    self.game_monitor.add_game(nba_id)
                    added += 1

            # Reset triggers for new day (check before setting _current_date)
            if self._current_date != date_str:
                logger.info(f"New day detected, resetting triggers")
                self.trigger_engine.reset()

            self._current_date = date_str
            self._schedule_refreshed = datetime.now()
            self._stats.games_monitored = len(self.game_monitor._monitored_games)

            logger.info(f"Added {added} games to monitoring for {date_str}")

        except Exception as e:
            logger.error(f"Failed to refresh schedule: {e}")

    def _process_event(self, event: TriggerEvent) -> None:
        """Process a trigger event."""
        if not event.prediction:
            logger.warning(f"No prediction for event {event.trigger_key}")
            return

        # Generate post
        try:
            # Always fetch odds for betting recommendations
            odds = self._fetch_odds(event.game_state, event.prediction)

            # Get team names
            home_team = event.game_state.home_tricode or "Home"
            away_team = event.game_state.away_tricode or "Away"

            # Create recommendations (returns tuple of recommended, passed)
            recommendations, passed_bets = self.post_generator.create_recommendations_from_prediction(
                event.prediction, odds, home_team=home_team, away_team=away_team
            )

            if event.trigger_type == TriggerType.HALFTIME:
                post = self.post_generator.generate_halftime_post(
                    event.prediction,
                    event.game_state,
                    recommendations,
                    passed_bets,
                )
            elif event.trigger_type == TriggerType.Q3_5MIN:
                post = self.post_generator.generate_q3_post(
                    event.prediction,
                    event.game_state,
                    recommendations,
                    passed_bets,
                )
            else:
                logger.warning(f"Unknown trigger type: {event.trigger_type}")
                return

            # Post to platforms
            self._post_to_platforms(post, event)

        except Exception as e:
            logger.error(f"Failed to process event: {e}")

    def _fetch_odds(self, game_state: GameState, prediction: dict) -> Optional[dict]:
        """Fetch odds for a game from the Odds API."""
        try:
            from src.odds import fetch_nba_odds_snapshot, OddsAPIError

            logger.info(f"Fetching odds for {game_state.display_name}")

            snapshot = fetch_nba_odds_snapshot(
                home_name=game_state.home_team or game_state.home_tricode,
                away_name=game_state.away_team or game_state.away_tricode,
            )

            odds = {
                "total_points": snapshot.total_points,
                "total_over_odds": snapshot.total_over_odds,
                "total_under_odds": snapshot.total_under_odds,
                "spread_home": snapshot.spread_home,
                "spread_home_odds": snapshot.spread_home_odds,
                "spread_away_odds": snapshot.spread_away_odds,
                "moneyline_home": snapshot.moneyline_home,
                "moneyline_away": snapshot.moneyline_away,
                "team_total_home": snapshot.team_total_home,
                "team_total_home_over_odds": snapshot.team_total_home_over_odds,
                "team_total_home_under_odds": snapshot.team_total_home_under_odds,
                "team_total_away": snapshot.team_total_away,
                "team_total_away_over_odds": snapshot.team_total_away_over_odds,
                "team_total_away_under_odds": snapshot.team_total_away_under_odds,
                "bookmaker": snapshot.bookmaker,
            }

            logger.info(
                f"Odds fetched: Total {snapshot.total_points or 'N/A'}, "
                f"Spread {snapshot.spread_home or 'N/A'}, "
                f"ML {snapshot.moneyline_home or 'N/A'}/{snapshot.moneyline_away or 'N/A'}, "
                f"Team Totals {snapshot.team_total_home or 'N/A'}/{snapshot.team_total_away or 'N/A'}"
            )

            return odds

        except OddsAPIError as e:
            logger.warning(f"Odds API error: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to fetch odds: {e}")
            return None

    def _post_to_platforms(self, post, event: TriggerEvent) -> None:
        """Post to configured platforms."""
        for platform in self.platforms:
            if platform == "discord" and self.discord:
                result = self.discord.post_message(post.content)
                if result.success:
                    self._stats.posts_successful += 1
                    self.trigger_engine.mark_posted(event)
                    logger.info(f"Posted to Discord: {event.trigger_key}")
                else:
                    self._stats.posts_failed += 1
                    logger.error(f"Failed to post to Discord: {result.error}")

    def _cleanup(self) -> None:
        """Clean up resources."""
        if self.discord:
            self.discord.close()

    # Manual control methods

    def add_game(self, game_id: str) -> None:
        """Manually add a game to monitoring."""
        self.game_monitor.add_game(game_id)

    def add_game_with_odds(self, game_id: str) -> None:
        """Add a game to monitoring and queue it for odds fetching.

        Only games added with this method will have odds fetched when
        triggers fire. This prevents wasting Odds API credits on games
        that weren't specifically requested.

        Args:
            game_id: NBA game ID to add
        """
        self.game_monitor.add_game(game_id)
        self.trigger_engine.add_manually_queued_game(game_id)
        logger.info(f"Added {game_id} with odds fetching enabled")

    def remove_game(self, game_id: str) -> None:
        """Manually remove a game from monitoring."""
        self.game_monitor.remove_game(game_id)
        self.trigger_engine.remove_manually_queued_game(game_id)

    def get_game_state(self, game_id: str) -> Optional[GameState]:
        """Get current state for a game."""
        return self.game_monitor.get_game_state(game_id)

    def force_trigger_check(self, game_id: str) -> Optional[TriggerEvent]:
        """Force a trigger check for a specific game."""
        state = self.game_monitor.get_game_state(game_id)
        if not state:
            return None

        events = self.trigger_engine.evaluate_game(state, self.prediction_callback)
        if events:
            return events[0]
        return None


def create_service_from_env() -> AutomationService:
    """
    Create automation service from environment variables.

    Required:
        DISCORD_WEBHOOK_URL: Discord webhook URL

    Optional:
        POLL_INTERVAL: Polling interval in seconds (default: 30)
        INCLUDE_BETTING: Include betting recommendations (default: true)
    """
    import os

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        raise ValueError("DISCORD_WEBHOOK_URL environment variable required")

    poll_interval = int(os.environ.get("POLL_INTERVAL", "30"))
    include_betting = os.environ.get("INCLUDE_BETTING", "true").lower() == "true"

    return AutomationService(
        discord_webhook_url=webhook_url,
        poll_interval=poll_interval,
        include_betting=include_betting,
    )


__all__ = ["AutomationService", "ServiceStats", "create_service_from_env"]

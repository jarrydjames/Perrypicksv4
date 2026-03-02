"""
Trigger Detection for PerryPicks

Evaluates game states to detect trigger conditions (halftime, Q3)
and fires prediction events with deduplication.

Usage:
    from src.automation.triggers import TriggerEngine, TriggerType

    engine = TriggerEngine()
    events = engine.evaluate_all(game_monitor, prediction_callback)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Optional, Set

from src.automation.game_state import GameState, GameStateMonitor

logger = logging.getLogger(__name__)


class TriggerType(str, Enum):
    """Types of triggers that can fire predictions."""

    PREGAME = "pregame"
    HALFTIME = "halftime"
    Q3_5MIN = "q3_5min"

    def __str__(self) -> str:
        return self.value


@dataclass
class TriggerEvent:
    """Represents a triggered prediction event."""

    game_id: str
    trigger_type: TriggerType
    game_state: GameState
    prediction: Optional[dict] = None
    odds: Optional[dict] = None  # Odds data from API
    timestamp: datetime = field(default_factory=datetime.utcnow)
    posted: bool = False
    error: Optional[str] = None

    @property
    def trigger_key(self) -> str:
        """Unique key for deduplication."""
        return f"{self.game_id}_{self.trigger_type}"


class TriggerEngine:
    """
    Evaluates game states and fires prediction triggers.

    This engine:
    1. Checks each monitored game for trigger conditions
    2. Deduplicates triggers to prevent repeated predictions
    3. Calls prediction callbacks when triggers fire
    4. Only fetches odds for manually queued games (saves API credits)
    """

    def __init__(self):
        self._fired_triggers: Set[str] = set()
        self._pending_events: List[TriggerEvent] = []
        # Track manually queued games - only these fetch odds
        self._manually_queued_games: Set[str] = set()

    def add_manually_queued_game(self, game_id: str) -> None:
        """Add a game to the manually queued set (will fetch odds)."""
        self._manually_queued_games.add(game_id)
        logger.info(f"Marked {game_id} as manually queued (odds will be fetched)")

    def remove_manually_queued_game(self, game_id: str) -> None:
        """Remove a game from the manually queued set."""
        self._manually_queued_games.discard(game_id)

    def is_manually_queued(self, game_id: str) -> bool:
        """Check if a game is manually queued for odds fetching."""
        return game_id in self._manually_queued_games

    def reset(self) -> None:
        """Reset fired triggers (e.g., for a new day)."""
        self._fired_triggers.clear()
        self._pending_events.clear()
        logger.info("Trigger engine reset")

    def has_fired(self, game_id: str, trigger_type: TriggerType) -> bool:
        """Check if a trigger has already fired for a game."""
        key = f"{game_id}_{trigger_type}"
        return key in self._fired_triggers

    def mark_fired(self, game_id: str, trigger_type: TriggerType) -> None:
        """Mark a trigger as fired."""
        key = f"{game_id}_{trigger_type}"
        self._fired_triggers.add(key)

    def check_halftime_trigger(self, state: GameState) -> bool:
        """Check if halftime trigger should fire.
        
        Includes catch-up for games that started before bot started:
        - If already in Q3+ and halftime trigger not fired, fire it (catch-up)
        """
        if self.has_fired(state.game_id, TriggerType.HALFTIME):
            return False
        
        # Normal halftime detection
        if state.is_halftime:
            return True
        
        # Catch-up: if already past halftime (Q3+) and trigger hasn't fired, fire it now
        # This handles the case where bot was restarted during a game
        if state.period >= 3 and state.is_live:
            logger.info(f"Catch-up: halftime trigger firing for {state.display_name} (already in Q{state.period})")
            return True
        
        return False

    def check_q3_trigger(self, state: GameState) -> bool:
        """Check if Q3-5min trigger should fire."""
        if self.has_fired(state.game_id, TriggerType.Q3_5MIN):
            return False

        # Must be in Q3
        if state.period != 3:
            return False

        # Must be live (not halftime)
        if not state.is_live:
            return False

        # 5 minutes or less remaining
        return state.minutes_remaining_in_period <= 5

    def evaluate_game(
        self,
        state: GameState,
        prediction_callback: Optional[
            Callable[[str, TriggerType, GameState], Optional[dict]]
        ] = None,
    ) -> List[TriggerEvent]:
        """
        Evaluate a single game for triggers.

        Args:
            state: Current game state
            prediction_callback: Function to generate prediction

        Returns:
            List of triggered events
        """
        events = []

        # Check halftime trigger
        if self.check_halftime_trigger(state):
            logger.info(f"Half time trigger fired for {state.display_name}")

            event = TriggerEvent(
                game_id=state.game_id,
                trigger_type=TriggerType.HALFTIME,
                game_state=state,
            )

            # Get prediction if callback provided
            if prediction_callback:
                try:
                    event.prediction = prediction_callback(
                        state.game_id, TriggerType.HALFTIME, state
                    )
                except Exception as e:
                    logger.error(f"Prediction callback failed: {e}")
                    event.error = str(e)

            self.mark_fired(state.game_id, TriggerType.HALFTIME)
            events.append(event)

        # Check Q3 trigger
        elif self.check_q3_trigger(state):
            logger.info(f"Q3 trigger fired for {state.display_name}")

            event = TriggerEvent(
                game_id=state.game_id,
                trigger_type=TriggerType.Q3_5MIN,
                game_state=state,
            )

            # Get prediction if callback provided
            if prediction_callback:
                try:
                    event.prediction = prediction_callback(
                        state.game_id, TriggerType.Q3_5MIN, state
                    )
                except Exception as e:
                    logger.error(f"Prediction callback failed: {e}")
                    event.error = str(e)

            self.mark_fired(state.game_id, TriggerType.Q3_5MIN)
            events.append(event)

        return events

    def evaluate_all(
        self,
        monitor: GameStateMonitor,
        prediction_callback: Optional[
            Callable[[str, TriggerType, GameState], Optional[dict]]
        ] = None,
    ) -> List[TriggerEvent]:
        """
        Evaluate all monitored games for triggers.

        Args:
            monitor: GameStateMonitor instance
            prediction_callback: Function to generate predictions

        Returns:
            List of all triggered events
        """
        all_events = []

        for game_id in list(monitor._monitored_games):
            state = monitor.get_game_state(game_id)
            if state:
                events = self.evaluate_game(state, prediction_callback)
                all_events.extend(events)

        self._pending_events.extend(all_events)
        return all_events

    def get_pending_events(self) -> List[TriggerEvent]:
        """Get all pending events that haven't been posted."""
        return [e for e in self._pending_events if not e.posted]

    def mark_posted(self, event: TriggerEvent) -> None:
        """Mark an event as posted."""
        event.posted = True

    def clear_posted_events(self) -> None:
        """Remove all posted events from pending list."""
        self._pending_events = [e for e in self._pending_events if not e.posted]

    def cleanup_finished_games(self, finished_game_ids: Set[str]) -> None:
        """Remove triggers for finished games to prevent memory leaks."""
        if not finished_game_ids:
            return

        # Remove fired trigger keys for finished games
        keys_to_remove = set()
        for key in self._fired_triggers:
            for gid in finished_game_ids:
                if key.startswith(f"{gid}_"):
                    keys_to_remove.add(key)

        self._fired_triggers -= keys_to_remove

        # Remove pending events for finished games
        self._pending_events = [
            e for e in self._pending_events if e.game_id not in finished_game_ids
        ]

        logger.debug(f"Cleaned up {len(keys_to_remove)} triggers for {len(finished_game_ids)} finished games")


__all__ = ["TriggerType", "TriggerEvent", "TriggerEngine"]

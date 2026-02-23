"""
Historical Data Manager for Pregame Feature Extraction

Loads historical game data and provides methods to calculate temporal features:
- Head-to-head (H2H) lookup
- Schedule strength calculation
- Rest days tracking
- Recent form (last N games)
- Home/road win % calculation

Data source: data/processed/final_features.parquet
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Optional, List
from datetime import datetime
from collections import defaultdict
import logging

from src.modeling.types import TEAM_ID_TO_TRICODE, TRICODE_TO_TEAM_ID

logger = logging.getLogger(__name__)


class HistoricalDataManager:
    """
    Manage historical game data for feature extraction.

    Provides cached access to:
    - Team game histories
    - Head-to-head matchups
    - Schedule features (rest days, B2B)
    - Recent form metrics
    """

    def __init__(self, historical_path: str = 'data/processed/final_features.parquet'):
        """
        Initialize historical data manager.

        Args:
            historical_path: Path to historical features parquet file
        """
        self.historical_path = Path(historical_path)
        self.games_df: Optional[pd.DataFrame] = None
        self._team_games: Dict[int, pd.DataFrame] = {}
        self._h2h_cache: Dict[tuple, pd.DataFrame] = {}

    def load_data(self) -> bool:
        """Load historical data from parquet file."""
        if self.historical_path.exists():
            logger.info(f"Loading historical data from {self.historical_path}")
            self.games_df = pd.read_parquet(self.historical_path)

            # Convert game_date to datetime
            self.games_df['game_date'] = pd.to_datetime(self.games_df['game_date'])

            # Add tricode columns
            self.games_df['home_team'] = self.games_df['home_team_id'].map(TEAM_ID_TO_TRICODE)
            self.games_df['away_team'] = self.games_df['away_team_id'].map(TEAM_ID_TO_TRICODE)

            # Sort by date
            self.games_df = self.games_df.sort_values('game_date')

            logger.info(f"Loaded {len(self.games_df)} games")
            return True
        else:
            logger.warning(f"Historical data file not found: {self.historical_path}")
            return False

    def get_team_games(
        self,
        team_id: int,
        before_date: Optional[datetime] = None,
        n: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Get games for a team before a date.

        Args:
            team_id: Team ID
            before_date: Only include games before this date
            n: Limit to N most recent games

        Returns:
            DataFrame of team games
        """
        if self.games_df is None:
            if not self.load_data():
                return pd.DataFrame()

        # Check cache
        if team_id not in self._team_games:
            team_games = self.games_df[
                (self.games_df['home_team_id'] == team_id) |
                (self.games_df['away_team_id'] == team_id)
            ].copy()
            self._team_games[team_id] = team_games

        games = self._team_games[team_id].copy()

        # Filter by date
        if before_date:
            games = games[games['game_date'] < before_date]

        # Sort by date descending
        games = games.sort_values('game_date', ascending=False)

        # Limit to N games
        if n is not None and len(games) > n:
            games = games.head(n)

        return games

    def get_h2h_games(
        self,
        team_a_id: int,
        team_b_id: int,
        before_date: Optional[datetime] = None,
        n: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Get head-to-head games between two teams.

        Args:
            team_a_id: First team ID
            team_b_id: Second team ID
            before_date: Only include games before this date
            n: Limit to N most recent games

        Returns:
            DataFrame of H2H games
        """
        if self.games_df is None:
            if not self.load_data():
                return pd.DataFrame()

        # Check cache
        cache_key = tuple(sorted([team_a_id, team_b_id]))
        if cache_key not in self._h2h_cache:
            h2h_games = self.games_df[
                (
                    (self.games_df['home_team_id'] == team_a_id) &
                    (self.games_df['away_team_id'] == team_b_id)
                ) | (
                    (self.games_df['home_team_id'] == team_b_id) &
                    (self.games_df['away_team_id'] == team_a_id)
                )
            ].copy()
            self._h2h_cache[cache_key] = h2h_games

        games = self._h2h_cache[cache_key].copy()

        if before_date:
            games = games[games['game_date'] < before_date]

        games = games.sort_values('game_date', ascending=False)

        if n is not None and len(games) > n:
            games = games.head(n)

        return games

    def calculate_h2h_features(
        self,
        home_team_id: int,
        away_team_id: int,
        game_date: datetime
    ) -> Dict[str, float]:
        """
        Calculate H2H features for a game.

        Returns 12 features capturing head-to-head history.
        """
        features = {}

        h2h_games = self.get_h2h_games(home_team_id, away_team_id, before_date=game_date)

        if len(h2h_games) == 0:
            return self._default_h2h_features()

        # Calculate wins from home team's perspective
        h2h_games['home_team_won'] = (
            ((h2h_games['home_team_id'] == home_team_id) & (h2h_games['margin'] > 0)) |
            ((h2h_games['away_team_id'] == home_team_id) & (h2h_games['margin'] < 0))
        )

        h2h_home_wins = h2h_games['home_team_won'].sum()
        h2h_away_wins = len(h2h_games) - h2h_home_wins
        h2h_total = float(len(h2h_games))

        features['h2h_home_wins'] = float(h2h_home_wins)
        features['h2h_away_wins'] = float(h2h_away_wins)
        features['h2h_total_games'] = h2h_total
        features['h2h_home_win_pct'] = h2h_home_wins / h2h_total if h2h_total > 0 else 0.5

        # Recent H2H (last 5 games)
        h2h_recent = h2h_games.head(5)
        if len(h2h_recent) > 0:
            h2h_recent_home_wins = h2h_recent['home_team_won'].sum()
            h2h_recent_total = float(len(h2h_recent))
            features['h2h_recent_home_wins'] = float(h2h_recent_home_wins)
            features['h2h_recent_away_wins'] = h2h_recent_total - h2h_recent_home_wins
            features['h2h_recent_total'] = h2h_recent_total
            features['h2h_recent_home_win_pct'] = h2h_recent_home_wins / h2h_recent_total
        else:
            features.update(self._default_h2h_features())

        # Differentials
        features['h2h_wins_diff'] = features['h2h_home_wins'] - features['h2h_away_wins']
        features['h2h_recent_wins_diff'] = features['h2h_recent_home_wins'] - features['h2h_recent_away_wins']

        return features

    def calculate_schedule_features(
        self,
        home_team_id: int,
        away_team_id: int,
        game_date: datetime
    ) -> Dict[str, float]:
        """
        Calculate schedule features (rest days, B2B).

        Returns 7 features.
        """
        features = {}

        home_rest = self._calculate_rest_days(home_team_id, game_date)
        away_rest = self._calculate_rest_days(away_team_id, game_date)

        features['home_rest_days'] = float(home_rest)
        features['away_rest_days'] = float(away_rest)
        features['rest_days_diff'] = features['home_rest_days'] - features['away_rest_days']

        features['home_is_b2b'] = 1.0 if home_rest == 1 else 0.0
        features['away_is_b2b'] = 1.0 if away_rest == 1 else 0.0
        features['home_b2b_x_home'] = features['home_is_b2b'] * 1.0
        features['b2b_diff'] = features['home_is_b2b'] - features['away_is_b2b']

        return features

    def calculate_recent_form(
        self,
        home_team_id: int,
        away_team_id: int,
        game_date: datetime
    ) -> Dict[str, float]:
        """
        Calculate recent form features (last 10 games).

        Returns 12 features.
        """
        features = {}

        home_recent = self.get_team_games(home_team_id, before_date=game_date, n=10)
        away_recent = self.get_team_games(away_team_id, before_date=game_date, n=10)

        # Home team recent form
        if len(home_recent) > 0:
            features.update(self._extract_team_form(home_recent, home_team_id, 'home'))
        else:
            features.update(self._default_form_features('home'))

        # Away team recent form
        if len(away_recent) > 0:
            features.update(self._extract_team_form(away_recent, away_team_id, 'away'))
        else:
            features.update(self._default_form_features('away'))

        # Differentials
        features['recent_points_diff'] = features.get('home_recent_points', 0) - features.get('away_recent_points', 0)
        features['recent_margin_diff'] = features.get('home_recent_margin', 0) - features.get('away_recent_margin', 0)
        features['recent_wins_diff'] = features.get('home_recent_wins', 0.5) - features.get('away_recent_wins', 0.5)

        return features

    def _calculate_rest_days(self, team_id: int, game_date: datetime) -> int:
        """Calculate rest days since last game."""
        team_games = self.get_team_games(team_id, before_date=game_date, n=1)

        if len(team_games) == 0:
            return 7  # Default if no previous game

        last_game = team_games.iloc[0]
        last_date = last_game['game_date']

        days_diff = (game_date - last_date).days
        return max(days_diff, 1)

    def _extract_team_form(
        self,
        games: pd.DataFrame,
        team_id: int,
        prefix: str
    ) -> Dict[str, float]:
        """Extract team form features from games."""
        features = {}

        games['team_score'] = np.where(
            games['home_team_id'] == team_id,
            games['home_score'],
            games['away_score']
        )
        games['team_allowed'] = np.where(
            games['home_team_id'] == team_id,
            games['away_score'],
            games['home_score']
        )
        games['team_margin'] = np.where(
            games['home_team_id'] == team_id,
            games['margin'],
            -games['margin']
        )
        games['team_win'] = (
            ((games['home_team_id'] == team_id) & (games['margin'] > 0)) |
            ((games['away_team_id'] == team_id) & (games['margin'] < 0))
        )

        features[f'{prefix}_recent_points'] = float(games['team_score'].mean())
        features[f'{prefix}_recent_allowed'] = float(games['team_allowed'].mean())
        features[f'{prefix}_recent_margin'] = float(games['team_margin'].mean())
        features[f'{prefix}_recent_wins'] = float(games['team_win'].mean())

        return features

    def _default_h2h_features(self) -> Dict[str, float]:
        return {
            'h2h_home_wins': 5.0,
            'h2h_away_wins': 5.0,
            'h2h_total_games': 10.0,
            'h2h_home_win_pct': 0.5,
            'h2h_recent_home_wins': 2.0,
            'h2h_recent_away_wins': 2.0,
            'h2h_recent_total': 5.0,
            'h2h_recent_home_win_pct': 0.5,
            'h2h_wins_diff': 0.0,
            'h2h_recent_wins_diff': 0.0,
        }

    def _default_form_features(self, prefix: str) -> Dict[str, float]:
        return {
            f'{prefix}_recent_points': 0.0,
            f'{prefix}_recent_allowed': 0.0,
            f'{prefix}_recent_margin': 0.0,
            f'{prefix}_recent_wins': 0.5,
        }


# Global instance
_historical_manager: Optional[HistoricalDataManager] = None


def get_historical_manager() -> Optional[HistoricalDataManager]:
    """Get or create global historical data manager."""
    global _historical_manager

    if _historical_manager is None:
        _historical_manager = HistoricalDataManager()
        _historical_manager.load_data()

    return _historical_manager


__all__ = [
    "HistoricalDataManager",
    "get_historical_manager",
]

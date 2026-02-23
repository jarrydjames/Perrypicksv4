"""
Temporal Feature Store for REPTAR

This module provides access to pre-computed temporal features from
historical game data. These features are essential for achieving the
documented 75% win accuracy.

Features include:
- Rolling averages (5/10/20 game windows)
- Exponential weighted moving averages
- Streaks and trends
- Rest days and back-to-back flags
- Home/away splits
- Team efficiency stats

Usage:
    from src.features.temporal_store import TemporalFeatureStore

    store = TemporalFeatureStore()
    features = store.get_team_features("BOS", pd.Timestamp("2026-02-11"))
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Default paths
DEFAULT_DATA_PATH = Path("data/processed/halftime_with_refined_temporal.parquet")
DEFAULT_TEAM_ID_MAP_PATH = Path("data/processed/team_tricode_to_custom_id.json")
DEFAULT_METRICS_PATH = Path("reports/champion_runs/latest/halftime_fold_metrics.csv")

# Recency features used for runtime lookups
RECENCY_BASE_FEATURES = [
    "pts_scored_avg_5",
    "pts_allowed_avg_5",
    "margin_avg_5",
    "current_streak",
    "days_since_last",
    "is_back_to_back",
    "efg",
    "tor",
    "tpar",
    "ftr",
    "orbp",
]

# Critical features for feature health checks
CRITICAL_FEATURES = [
    "home_team_id",
    "away_team_id",
    "home_pts_scored_avg_5",
    "away_pts_scored_avg_5",
    "home_efg",
    "away_efg",
]


@dataclass
class TeamFeatures:
    """Container for team temporal features."""
    team_id: float
    team_tri: str
    game_date: Optional[pd.Timestamp]
    features: Dict[str, float]

    def get(self, feature_name: str, default: float = 0.0) -> float:
        """Get a feature value with default."""
        return self.features.get(feature_name, default)


class TemporalFeatureStore:
    """
    Feature store for pre-computed temporal features.

    This class loads the refined temporal features from parquet and provides
    efficient lookups for team features at runtime.
    """

    def __init__(
        self,
        data_path: Path = None,
        team_id_map_path: Path = None,
    ):
        self.data_path = data_path or DEFAULT_DATA_PATH
        self.team_id_map_path = team_id_map_path or DEFAULT_TEAM_ID_MAP_PATH

        self._df: Optional[pd.DataFrame] = None
        self._team_id_map: Dict[str, float] = {}
        self._loaded = False

    def load(self) -> bool:
        """Load the feature store from disk."""
        if self._loaded:
            return True

        # Load team ID mapping
        if self.team_id_map_path.exists():
            with open(self.team_id_map_path, 'r') as f:
                tri_to_id = json.load(f)
            self._team_id_map = {k: float(v) for k, v in tri_to_id.items()}
            logger.info(f"Loaded team ID mapping for {len(self._team_id_map)} teams")
        else:
            logger.warning(f"Team ID map not found at {self.team_id_map_path}")

        # Load refined temporal features
        if not self.data_path.exists():
            logger.error(f"Feature store not found at {self.data_path}")
            return False

        try:
            self._df = pd.read_parquet(self.data_path)
            self._df['game_date'] = pd.to_datetime(
                self._df['game_date'], errors='coerce', utc=True
            )
            self._loaded = True
            logger.info(f"Loaded {len(self._df)} games with {len(self._df.columns)} features")
            return True
        except Exception as e:
            logger.error(f"Failed to load feature store: {e}")
            return False

    def ensure_loaded(self) -> None:
        """Ensure the feature store is loaded."""
        if not self._loaded:
            if not self.load():
                raise RuntimeError("Failed to load temporal feature store")

    @property
    def df(self) -> pd.DataFrame:
        """Get the underlying dataframe."""
        self.ensure_loaded()
        return self._df

    def team_tricode_to_id(self, tricode: str) -> float:
        """Convert team tricode to numeric ID."""
        self.ensure_loaded()
        return self._team_id_map.get(tricode.upper(), 0.0)

    def get_default_features(self, prefix: str) -> Dict[str, float]:
        """Get default feature values when no historical data is available."""
        defaults = {
            f"{prefix}_pts_scored_avg_5": 54.0,
            f"{prefix}_pts_allowed_avg_5": 54.0,
            f"{prefix}_margin_avg_5": 0.0,
            f"{prefix}_current_streak": 0.0,
            f"{prefix}_days_since_last": 7.0,
            f"{prefix}_is_back_to_back": 0.0,
            f"{prefix}_efg": 0.52,
            f"{prefix}_tor": 0.12,
            f"{prefix}_tpar": 0.35,
            f"{prefix}_ftr": 0.25,
            f"{prefix}_orbp": 0.25,
            # Extended features
            f"{prefix}_pts_scored_avg_10": 54.0,
            f"{prefix}_pts_allowed_avg_10": 54.0,
            f"{prefix}_margin_avg_10": 0.0,
            f"{prefix}_pts_scored_avg_20": 54.0,
            f"{prefix}_pts_allowed_avg_20": 54.0,
            f"{prefix}_margin_avg_20": 0.0,
            f"{prefix}_pts_scored_ewm_5": 54.0,
            f"{prefix}_pts_allowed_ewm_5": 54.0,
            f"{prefix}_margin_ewm_5": 0.0,
            f"{prefix}_pts_scored_ewm_10": 54.0,
            f"{prefix}_pts_allowed_ewm_10": 54.0,
            f"{prefix}_margin_ewm_10": 0.0,
            f"{prefix}_pts_scored_ewm_20": 54.0,
            f"{prefix}_pts_allowed_ewm_20": 54.0,
            f"{prefix}_margin_ewm_20": 0.0,
            f"{prefix}_wins_5": 2.5,
            f"{prefix}_wins_10": 5.0,
            f"{prefix}_wins_20": 10.0,
            f"{prefix}_is_3_in_4": 0.0,
            f"{prefix}_pts_scored_home_avg_5": 54.0,
            f"{prefix}_margin_home_avg_5": 0.0,
            f"{prefix}_pts_scored_away_avg_5": 54.0,
            f"{prefix}_margin_away_avg_5": 0.0,
            f"{prefix}_margin_trend_5": 0.0,
            f"{prefix}_pts_trend_5": 0.0,
            f"{prefix}_margin_std_5": 5.0,
            f"{prefix}_pts_scored_std_5": 5.0,
            f"{prefix}_games_played": 0.0,
        }
        return defaults

    def get_team_features(
        self,
        team_id: float,
        target_dt: pd.Timestamp,
        prefix: str,
    ) -> Dict[str, float]:
        """
        Get team temporal features as of a specific date.

        This finds the most recent game for this team before the target date
        and extracts the pre-computed temporal features.

        Args:
            team_id: Numeric team ID (0-29)
            target_dt: Target date (look for games before this)
            prefix: Feature prefix (e.g., "home" or "away")

        Returns:
            Dictionary of feature values
        """
        self.ensure_loaded()

        # Start with defaults
        features = self.get_default_features(prefix)
        features[f"{prefix}_team_id"] = float(team_id)

        if team_id <= 0:
            return features

        # Find the most recent game for this team before target date
        game_date_col = "game_date"

        # CRITICAL FIX: Validate column exists before filtering
        if game_date_col not in self._df.columns:
            logger.error(f"Column {game_date_col} not found in feature store columns: {list(self._df.columns)[:10]}")
            return features

        latest_row = None
        latest_date = None

        for side in ["home", "away"]:
            id_col = f"{side}_team_id"
            if id_col not in self._df.columns:
                continue

            subset = self._df[self._df[id_col] == team_id].copy()
            if subset.empty:
                continue

            subset = subset[subset[game_date_col] < target_dt]
            if subset.empty:
                continue

            idx = subset[game_date_col].idxmax()
            row = subset.loc[idx]
            row_date = row[game_date_col]

            if latest_date is None or row_date > latest_date:
                latest_date = row_date
                latest_row = row

        if latest_row is None:
            return features

        # Extract all features that start with the prefix
        for col in self._df.columns:
            if col.startswith(f"{prefix}_"):
                if col in latest_row:
                    val = pd.to_numeric(latest_row[col], errors='coerce')
                    if pd.notna(val):
                        features[col] = float(val)

        return features

    def get_team_features_by_tricode(
        self,
        tricode: str,
        target_dt: pd.Timestamp,
        prefix: str,
    ) -> Dict[str, float]:
        """Get team features by tricode."""
        team_id = self.team_tricode_to_id(tricode)
        return self.get_team_features(team_id, target_dt, prefix)

    def get_feature_columns(self) -> List[str]:
        """Get list of feature columns (excluding targets and metadata)."""
        self.ensure_loaded()

        exclude = {
            'game_id', 'season_end_yy', 'game_date',
            'h1_home', 'h1_away', 'h1_total', 'h1_margin',
            'h1_events', 'h1_n_2pt', 'h1_n_3pt', 'h1_n_turnover',
            'h1_n_rebound', 'h1_n_foul', 'h1_n_timeout', 'h1_n_sub',
            'home_efg', 'away_efg', 'h2_total', 'h2_margin',
            'final_total', 'final_margin',
            'home_tri', 'away_tri', 'home_team_id', 'away_team_id'
        }

        features = [col for col in self._df.columns if col not in exclude]

        # Only numeric features
        numeric_features = []
        for col in features:
            if self._df[col].dtype in ['int64', 'float64', 'int32', 'float32']:
                numeric_features.append(col)

        return numeric_features

    def get_training_data(
        self,
        before_date: pd.Timestamp,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, List[str]]:
        """
        Get training data for model fitting.

        Args:
            before_date: Only use games before this date

        Returns:
            X, y_total, y_margin, feature_names
        """
        self.ensure_loaded()

        train_df = self._df[self._df['game_date'] < before_date].copy()

        feature_cols = self.get_feature_columns()

        X = train_df[feature_cols].values
        X = np.nan_to_num(X, nan=0.0)

        y_total = train_df['h2_total'].values
        y_margin = train_df['h2_margin'].values

        return X, y_total, y_margin, feature_cols

    def get_feature_defaults(self) -> Dict[str, float]:
        """Get default values for all features."""
        defaults = {}
        defaults.update(self.get_default_features("home"))
        defaults.update(self.get_default_features("away"))

        # Add differential defaults
        for key, val in list(defaults.items()):
            if key.startswith("home_"):
                away_key = key.replace("home_", "away_")
                if away_key in defaults:
                    diff_key = key.replace("home_", "diff_")
                    defaults[diff_key] = 0.0

        return defaults


# Global instance
_feature_store: Optional[TemporalFeatureStore] = None


def get_feature_store() -> TemporalFeatureStore:
    """Get or create the global feature store instance."""
    global _feature_store

    if _feature_store is None:
        _feature_store = TemporalFeatureStore()
        _feature_store.load()

    return _feature_store


__all__ = [
    'TemporalFeatureStore',
    'TeamFeatures',
    'get_feature_store',
    'RECENCY_BASE_FEATURES',
    'CRITICAL_FEATURES',
]

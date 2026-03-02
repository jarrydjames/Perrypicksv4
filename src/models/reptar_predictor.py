"""
REPTAR Halftime Predictor

CatBoost-based halftime prediction model that integrates with the automation service.

This module provides predictions using the champion CatBoost model that was
selected after 48-hour production run with 51-fold walk-forward validation.

Performance:
- H2 Total MAE: 7.96 points
- H2 Margin MAE: 3.85 points
- Win Brier Score: 0.1023

Usage:
    from src.models.reptar_predictor import ReptarPredictor

    predictor = ReptarPredictor()
    pred = predictor.predict_from_game_id("0022500775")
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from scipy.stats import norm

from src.data.game_data import fetch_box, fetch_pbp_df, first_half_score, behavior_counts_1h, get_game_info, get_efficiency_stats_from_box

logger = logging.getLogger(__name__)

# Model paths - use absolute path based on project root
PROJECT_ROOT = Path(__file__).parent.parent.parent

# Prefer standalone folder (same pattern as Maximus/)
REPTAR_DIR = PROJECT_ROOT / "Reptar"
REPTAR_MODELS_DIR = REPTAR_DIR / "models"

# Back-compat fallback (legacy location)
LEGACY_MODEL_DIR = PROJECT_ROOT / "models_v3" / "halftime"

TOTAL_MODEL_PATH = (
    (REPTAR_MODELS_DIR / "catboost_h2_total.joblib")
    if (REPTAR_MODELS_DIR / "catboost_h2_total.joblib").exists()
    else (LEGACY_MODEL_DIR / "catboost_h2_total.joblib")
)
MARGIN_MODEL_PATH = (
    (REPTAR_MODELS_DIR / "catboost_h2_margin.joblib")
    if (REPTAR_MODELS_DIR / "catboost_h2_margin.joblib").exists()
    else (LEGACY_MODEL_DIR / "catboost_h2_margin.joblib")
)

# 80% confidence interval z-score
Z80 = 1.2815515655446004

# Required features for model validation
REQUIRED_FEATURES = [
    # H1 Stats (12 features)
    "h1_home", "h1_away", "h1_total", "h1_margin",
    "h1_events", "h1_n_2pt", "h1_n_3pt", "h1_n_turnover",
    "h1_n_rebound", "h1_n_foul", "h1_n_timeout", "h1_n_sub",
    # Efficiency Stats (10 features) - MUST be proportions (0-1 scale)
    "home_efg", "home_ftr", "home_tpar", "home_tor", "home_orbp",
    "away_efg", "away_ftr", "away_tpar", "away_tor", "away_orbp",
    # Team IDs (2 features)
    "home_team_id", "away_team_id",
    # Rolling 5-Game Stats (14 features)
    "home_pts_scored_avg_5", "home_pts_allowed_avg_5",
    "home_margin_avg_5", "home_wins_5", "home_current_streak_5",
    "home_days_since_last", "home_is_back_to_back",
    "away_pts_scored_avg_5", "away_pts_allowed_avg_5",
    "away_margin_avg_5", "away_wins_5", "away_current_streak_5",
    "away_days_since_last", "away_is_back_to_back",
]

# League average defaults for fallback
LEAGUE_AVERAGE_FEATURES = {
    "home_efg": 0.520, "home_ftr": 0.250, "home_tpar": 0.350,
    "home_tor": 0.125, "home_orbp": 0.250,
    "away_efg": 0.520, "away_ftr": 0.250, "away_tpar": 0.350,
    "away_tor": 0.125, "away_orbp": 0.250,
    "home_pts_scored_avg_5": 54.0, "home_pts_allowed_avg_5": 54.0,
    "home_margin_avg_5": 0.0, "home_wins_5": 2.5,
    "home_current_streak_5": 0.0, "home_days_since_last": 2,
    "home_is_back_to_back": 0,
    "away_pts_scored_avg_5": 54.0, "away_pts_allowed_avg_5": 54.0,
    "away_margin_avg_5": 0.0, "away_wins_5": 2.5,
    "away_current_streak_5": 0.0, "away_days_since_last": 2,
    "away_is_back_to_back": 0,
}


def validate_features(features: dict) -> List[str]:
    """Validate all required features are present and not None.

    Returns:
        List of issues found (empty if valid)
    """
    issues = []

    # Check for missing features
    missing = [f for f in REQUIRED_FEATURES if f not in features]
    if missing:
        issues.append(f"Missing features: {missing}")

    # Check for None/NaN values
    null_features = [f for f, v in features.items() if v is None or (isinstance(v, float) and pd.isna(v))]
    if null_features:
        issues.append(f"Null/NaN values in: {null_features}")

    # Validate efficiency stats are proportions (0-1 scale)
    for key in ["home_efg", "home_ftr", "home_tpar", "home_tor", "home_orbp",
                "away_efg", "away_ftr", "away_tpar", "away_tor", "away_orbp"]:
        val = features.get(key)
        if val is not None and (val < 0 or val > 1):
            issues.append(f"{key}={val} is out of proportion range [0,1]. Should be 0.XX not XX.X")

    return issues


def get_league_average_features() -> dict:
    """Return league-wide average features as fallback."""
    return LEAGUE_AVERAGE_FEATURES.copy()


@dataclass
class ReptarPrediction:
    """REPTAR halftime prediction result."""

    game_id: str
    home_team: str
    away_team: str

    # First half scores (actual)
    h1_home: int
    h1_away: int
    h1_total: int
    h1_margin: int

    # Second half predictions
    pred_2h_total: float
    pred_2h_margin: float
    pred_2h_home: float
    pred_2h_away: float

    # Final predictions
    pred_final_home: float
    pred_final_away: float
    pred_final_total: float
    pred_final_margin: float

    # Win probability
    home_win_prob: float
    away_win_prob: float

    # Confidence intervals (80%)
    total_q10: float
    total_q90: float
    margin_q10: float
    margin_q90: float


class ReptarPredictor:
    """
    REPTAR halftime predictor using CatBoost champion model.

    This predictor loads the pre-trained CatBoost models and provides
    predictions for second half scoring.
    """

    def __init__(
        self,
        total_model_path: Path = None,
        margin_model_path: Path = None,
    ):
        self.total_model_path = total_model_path or TOTAL_MODEL_PATH
        self.margin_model_path = margin_model_path or MARGIN_MODEL_PATH

        self._total_model = None
        self._total_features: List[str] = []
        self._margin_model = None
        self._margin_features: List[str] = []
        self._loaded = False

        # Residual sigmas for confidence intervals
        # Based on 48hr tuning results for retrained model:
        # - Final Total MAE: 12.95 points → RMSE ≈ 16
        # - Final Margin MAE: 4.29 points → RMSE ≈ 5.4
        self._sigma_total = 16.0   # RMSE for final total prediction
        self._sigma_margin = 5.4   # RMSE for final margin prediction

    @property
    def is_loaded(self) -> bool:
        """Check if models are loaded."""
        return self._loaded

    def load(self) -> bool:
        """Load the CatBoost models."""
        if self._loaded:
            return True

        try:
            # Load total model
            total_obj = joblib.load(self.total_model_path)
            self._total_model = total_obj["model"]
            self._total_features = total_obj["features"]
            logger.info(f"Loaded total model with {len(self._total_features)} features")

            # Load margin model
            margin_obj = joblib.load(self.margin_model_path)
            self._margin_model = margin_obj["model"]
            self._margin_features = margin_obj["features"]
            logger.info(f"Loaded margin model with {len(self._margin_features)} features")

            self._loaded = True
            return True

        except Exception as e:
            logger.error(f"Failed to load models: {e}")
            return False

    def ensure_loaded(self) -> None:
        """Ensure models are loaded."""
        if not self._loaded:
            if not self.load():
                raise RuntimeError("Failed to load REPTAR models")

    def predict(
        self,
        h1_home: int,
        h1_away: int,
        behavior: Optional[Dict[str, int]] = None,
        team_stats: Optional[Dict[str, float]] = None,
    ) -> Tuple[Dict[str, float], Dict[str, float]]:
        """
        Make a halftime prediction.

        Args:
            h1_home: Home team first half score
            h1_away: Away team first half score
            behavior: Optional behavior counts from play-by-play
            team_stats: Optional team efficiency and rolling stats.
                        If not provided, league averages are used.
                        IMPORTANT: efg, tor, tpar, orbp should be PROPORTIONS (0.52),
                        not percentages (52.0).

        Returns:
            Tuple of (features_dict, prediction_dict)

        WARNING: For accurate predictions, team_stats MUST include live efficiency stats
        from the current game's box score (get_efficiency_stats_from_box()). The model
        weights efficiency stats (efg, tor) at ~43% of the prediction - using historical
        averages instead of live game stats will produce incorrect predictions.

        For most use cases, prefer predict_from_game_id() which automatically fetches
        live efficiency stats.
        """
        self.ensure_loaded()

        # Default behavior counts if not provided
        if behavior is None:
            behavior = {}

        # Default team stats if not provided (league averages as PROPORTIONS)
        # CRITICAL: These must match training data format!
        if team_stats is None:
            team_stats = {}

        # Build feature row
        h1_total = h1_home + h1_away
        h1_margin = h1_home - h1_away

        features = {
            # H1 Stats (12 features) - available at halftime
            "h1_home": h1_home,
            "h1_away": h1_away,
            "h1_total": h1_total,
            "h1_margin": h1_margin,
            "h1_events": behavior.get("h1_events", 0),
            "h1_n_2pt": behavior.get("h1_n_2pt", 0),
            "h1_n_3pt": behavior.get("h1_n_3pt", 0),
            "h1_n_turnover": behavior.get("h1_n_turnover", 0),
            "h1_n_rebound": behavior.get("h1_n_rebound", 0),
            "h1_n_foul": behavior.get("h1_n_foul", 0),
            "h1_n_timeout": behavior.get("h1_n_timeout", 0),
            "h1_n_sub": behavior.get("h1_n_sub", 0),

            # Team Efficiency Stats (5 per team = 10 total)
            # CRITICAL: These must be PROPORTIONS (0.52), not percentages (52.0)!
            # Should come from live box score for best accuracy.
            "home_efg": team_stats.get("home_efg", 0.52),
            "home_ftr": team_stats.get("home_ftr", 0.25),
            "home_tpar": team_stats.get("home_tpar", 0.35),
            "home_tor": team_stats.get("home_tor", 0.12),
            "home_orbp": team_stats.get("home_orbp", 0.25),
            "away_efg": team_stats.get("away_efg", 0.50),
            "away_ftr": team_stats.get("away_ftr", 0.23),
            "away_tpar": team_stats.get("away_tpar", 0.35),
            "away_tor": team_stats.get("away_tor", 0.13),
            "away_orbp": team_stats.get("away_orbp", 0.24),

            # Team IDs (2 features)
            "home_team_id": team_stats.get("home_team_id", 0),
            "away_team_id": team_stats.get("away_team_id", 0),

            # Rolling 5-Game Stats (14 features) - from temporal feature store
            "home_pts_scored_avg_5": team_stats.get("home_pts_scored_avg_5", 54.0),
            "home_pts_allowed_avg_5": team_stats.get("home_pts_allowed_avg_5", 54.0),
            "home_margin_avg_5": team_stats.get("home_margin_avg_5", 0.0),
            "home_wins_5": team_stats.get("home_wins_5", 2.5),
            "home_current_streak_5": team_stats.get("home_current_streak_5", 0.0),
            "home_days_since_last": team_stats.get("home_days_since_last", 2),
            "home_is_back_to_back": team_stats.get("home_is_back_to_back", 0),
            "away_pts_scored_avg_5": team_stats.get("away_pts_scored_avg_5", 54.0),
            "away_pts_allowed_avg_5": team_stats.get("away_pts_allowed_avg_5", 54.0),
            "away_margin_avg_5": team_stats.get("away_margin_avg_5", 0.0),
            "away_wins_5": team_stats.get("away_wins_5", 2.5),
            "away_current_streak_5": team_stats.get("away_current_streak_5", 0.0),
            "away_days_since_last": team_stats.get("away_days_since_last", 2),
            "away_is_back_to_back": team_stats.get("away_is_back_to_back", 0),
        }

        # Create DataFrame
        df = pd.DataFrame([features])

        # Ensure all features are present (fill missing with 0)
        # CRITICAL FIX: Fill missing for BOTH total and margin features
        for feat in self._total_features + self._margin_features:
            if feat not in df.columns:
                df[feat] = 0

        # Validate features before prediction
        issues = validate_features(features)
        if issues:
            logger.error(f"Feature validation failed, cannot predict: {issues}")
            raise ValueError(f"Invalid features for prediction: {issues}")

        # Predict H2
        X_total = df[self._total_features]
        X_margin = df[self._margin_features]

        pred_2h_total = float(self._total_model.predict(X_total)[0])
        pred_2h_margin = float(self._margin_model.predict(X_margin)[0])

        # CRITICAL FIX: Validate predictions are finite (not NaN/Inf)
        if not np.isfinite(pred_2h_total) or not np.isfinite(pred_2h_margin):
            logger.error(f"Model produced non-finite predictions: total={pred_2h_total}, margin={pred_2h_margin}")
            raise ValueError("Model produced invalid (NaN/Inf) predictions")

        # Calculate H2 scores
        h2_home = (pred_2h_total + pred_2h_margin) / 2.0
        h2_away = (pred_2h_total - pred_2h_margin) / 2.0

        # Calculate final scores
        final_home = h1_home + h2_home
        final_away = h1_away + h2_away
        final_total = final_home + final_away
        final_margin = final_home - final_away

        # Win probability using normal distribution
        # H1 margin + predicted H2 margin = final margin
        # Win prob = P(final margin > 0)
        # CRITICAL FIX: Prevent division by zero with minimum sigma
        sigma_margin_safe = max(self._sigma_margin, 0.1)
        home_win_prob = 1.0 - norm.cdf(0, loc=final_margin, scale=sigma_margin_safe)

        # 80% confidence intervals with heteroscedasticity adjustment
        # Higher predictions have more uncertainty
        total_adjusted_sigma = self._sigma_total * (1 + abs(final_total - 220) / 500)
        margin_adjusted_sigma = self._sigma_margin * (1 + abs(final_margin) / 50)

        total_q10 = final_total - Z80 * total_adjusted_sigma
        total_q90 = final_total + Z80 * total_adjusted_sigma
        margin_q10 = final_margin - Z80 * margin_adjusted_sigma
        margin_q90 = final_margin + Z80 * margin_adjusted_sigma

        prediction = {
            "h1_home": h1_home,
            "h1_away": h1_away,
            "h1_total": h1_total,
            "h1_margin": h1_margin,
            "pred_2h_total": pred_2h_total,
            "pred_2h_margin": pred_2h_margin,
            "pred_2h_home": h2_home,
            "pred_2h_away": h2_away,
            "pred_final_home": final_home,
            "pred_final_away": final_away,
            "pred_final_total": final_total,
            "pred_final_margin": final_margin,
            "home_win_prob": home_win_prob,
            "away_win_prob": 1.0 - home_win_prob,
            "total_q10": total_q10,
            "total_q90": total_q90,
            "margin_q10": margin_q10,
            "margin_q90": margin_q90,
        }

        return features, prediction

    def predict_from_game_id(
        self,
        game_id: str,
    ) -> Optional[ReptarPrediction]:
        """
        Make a prediction from a game ID by fetching live data.

        Args:
            game_id: NBA game ID

        Returns:
            ReptarPrediction or None if prediction failed
        """
        self.ensure_loaded()

        try:
            # Fetch game data
            box = fetch_box(game_id)

            # CRITICAL FIX: Validate box score structure before processing
            if not box or not box.get("homeTeam") or not box.get("awayTeam"):
                logger.error(f"Invalid box score data for {game_id}")
                return None

            pbp = fetch_pbp_df(game_id)
            info = get_game_info(box)

            # Extract halftime scores
            h1_home, h1_away = first_half_score(box)
            if h1_home == 0 and h1_away == 0:
                logger.error(f"Could not get first half scores for {game_id}")
                return None

            # Extract behavior counts
            behavior = behavior_counts_1h(pbp)

            # Get efficiency stats from LIVE BOX SCORE (important for accurate predictions!)
            efficiency_stats = get_efficiency_stats_from_box(box)

            # Fetch team IDs and rolling stats from TemporalFeatureStore
            team_stats = self._fetch_team_stats(info)

            # Merge efficiency stats (from live game) with team stats (IDs and rolling averages)
            team_stats.update(efficiency_stats)

            # Make prediction with real team stats
            _, pred = self.predict(h1_home, h1_away, behavior, team_stats)

            return ReptarPrediction(
                game_id=game_id,
                home_team=info.get("home_tricode", "HOME"),
                away_team=info.get("away_tricode", "AWAY"),
                h1_home=int(pred["h1_home"]),
                h1_away=int(pred["h1_away"]),
                h1_total=int(pred["h1_total"]),
                h1_margin=int(pred["h1_margin"]),
                pred_2h_total=pred["pred_2h_total"],
                pred_2h_margin=pred["pred_2h_margin"],
                pred_2h_home=pred["pred_2h_home"],
                pred_2h_away=pred["pred_2h_away"],
                pred_final_home=pred["pred_final_home"],
                pred_final_away=pred["pred_final_away"],
                pred_final_total=pred["pred_final_total"],
                pred_final_margin=pred["pred_final_margin"],
                home_win_prob=pred["home_win_prob"],
                away_win_prob=pred["away_win_prob"],
                total_q10=pred["total_q10"],
                total_q90=pred["total_q90"],
                margin_q10=pred["margin_q10"],
                margin_q90=pred["margin_q90"],
            )

        except Exception as e:
            logger.error(f"Prediction failed for {game_id}: {e}")
            return None

    def _fetch_team_stats(self, info: dict) -> dict:
        """
        Fetch team stats from TemporalFeatureStore for team IDs and rolling stats.

        Args:
            info: Game info dict with home_tricode, away_tricode

        Returns:
            Dictionary of team stats including team IDs and efficiency stats
        """
        from src.features.temporal_store import get_feature_store
        import pandas as pd

        home_tri = info.get("home_tricode", "")
        away_tri = info.get("away_tricode", "")
        game_date = info.get("game_date") or datetime.utcnow()

        # Start with league average defaults
        team_stats = get_league_average_features()
        team_stats["home_team_id"] = 0
        team_stats["away_team_id"] = 0

        try:
            store = get_feature_store()

            # Get team IDs
            team_stats["home_team_id"] = store.team_tricode_to_id(home_tri)
            team_stats["away_team_id"] = store.team_tricode_to_id(away_tri)

            # Get rolling stats from temporal store (for past performance)
            target_dt = pd.Timestamp(game_date)
            # CRITICAL FIX: Handle both timezone-aware and naive datetimes
            if target_dt.tz is None:
                target_dt = target_dt.tz_localize('UTC')
            else:
                target_dt = target_dt.tz_convert('UTC')

            home_features = store.get_team_features_by_tricode(home_tri, target_dt, "home")
            away_features = store.get_team_features_by_tricode(away_tri, target_dt, "away")

            # Validate features exist and have values
            if home_features is None or len(home_features) == 0:
                logger.warning(f"No temporal data for {home_tri}, using league averages")
                home_features = {}
            else:
                # Check for None values
                null_keys = [k for k, v in home_features.items() if v is None]
                if null_keys:
                    logger.warning(f"Null features for {home_tri}: {null_keys}")

            if away_features is None or len(away_features) == 0:
                logger.warning(f"No temporal data for {away_tri}, using league averages")
                away_features = {}
            else:
                null_keys = [k for k, v in away_features.items() if v is None]
                if null_keys:
                    logger.warning(f"Null features for {away_tri}: {null_keys}")

            # Extract efficiency stats (use temporal data as baseline, but live box score will override)
            for key in ["efg", "ftr", "tpar", "tor", "orbp"]:
                home_val = home_features.get(f"home_{key}")
                away_val = away_features.get(f"away_{key}")
                if home_val is not None:
                    team_stats[f"home_{key}"] = home_val
                if away_val is not None:
                    team_stats[f"away_{key}"] = away_val

            # Extract rolling stats (note: temporal store uses 'current_streak' but model expects 'current_streak_5')
            for key in ["pts_scored_avg_5", "pts_allowed_avg_5", "margin_avg_5",
                        "wins_5", "days_since_last", "is_back_to_back"]:
                home_val = home_features.get(f"home_{key}")
                away_val = away_features.get(f"away_{key}")
                if home_val is not None:
                    team_stats[f"home_{key}"] = home_val
                if away_val is not None:
                    team_stats[f"away_{key}"] = away_val

            # Map 'current_streak' from store to 'current_streak_5' for model
            home_streak = home_features.get("home_current_streak")
            away_streak = away_features.get("away_current_streak")
            if home_streak is not None:
                team_stats["home_current_streak_5"] = home_streak
            if away_streak is not None:
                team_stats["away_current_streak_5"] = away_streak

            logger.debug(f"Team stats loaded: home_id={team_stats['home_team_id']}, away_id={team_stats['away_team_id']}")

        except Exception as e:
            logger.warning(f"Could not fetch team stats from store: {e}, using league average defaults")

        return team_stats

    def to_dict(self, pred: ReptarPrediction) -> Dict:
        """Convert prediction to dictionary for automation service."""
        return {
            "game_id": pred.game_id,
            "home_team": pred.home_team,
            "away_team": pred.away_team,
            "h1_home": pred.h1_home,
            "h1_away": pred.h1_away,
            "h1_total": pred.h1_total,
            "h1_margin": pred.h1_margin,
            "pred_2h_total": pred.pred_2h_total,
            "pred_2h_margin": pred.pred_2h_margin,
            "pred_2h_home": pred.pred_2h_home,
            "pred_2h_away": pred.pred_2h_away,
            "pred_final_home": pred.pred_final_home,
            "pred_final_away": pred.pred_final_away,
            "pred_final_total": pred.pred_final_total,
            "pred_final_margin": pred.pred_final_margin,
            "home_win_prob": pred.home_win_prob,
            "away_win_prob": pred.away_win_prob,
            "total_q10": pred.total_q10,
            "total_q90": pred.total_q90,
            "margin_q10": pred.margin_q10,
            "margin_q90": pred.margin_q90,
        }


# Global instance
_predictor: Optional[ReptarPredictor] = None


def get_predictor() -> ReptarPredictor:
    """Get or create the global predictor instance."""
    global _predictor

    if _predictor is None:
        _predictor = ReptarPredictor()
        _predictor.load()

    return _predictor


__all__ = ["ReptarPredictor", "ReptarPrediction", "get_predictor"]

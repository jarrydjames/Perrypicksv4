"""
Halftime Prediction Model

Predicts second half (H2) total points and margin using XGBoost models.
Allocates points to teams based on predicted margin.

The halftime model uses:
- First half scores (h1_home, h1_away)
- First half behavior counts (2pt, 3pt, turnovers, etc.)

Output:
- pred_2h_total: Predicted second half total points
- pred_2h_margin: Predicted second half margin (home - away)
- pred_2h_home: Predicted second half home points
- pred_2h_away: Predicted second half away points
- pred_final_*: Final game predictions (H1 + H2)

Usage:
    from src.models.halftime import predict_halftime, HalftimeModel

    # Simple usage
    result = predict_halftime(h1_home=58, h1_away=52, beh_counts={})

    # With game ID
    model = HalftimeModel()
    result = model.predict_from_game_id("0022500775")
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

import joblib
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# Model paths
HALFTIME_MODELS_DIR = Path("models_v3/halftime")
DEFAULT_TOTAL_MODEL = "xgboost_h2_total.joblib"
DEFAULT_MARGIN_MODEL = "xgboost_h2_margin.joblib"

# 80% interval z-score
Z80 = 1.2815515655446004


@dataclass
class HalftimePrediction:
    """Halftime prediction result."""
    game_id: str

    # First half (actual)
    h1_home: int
    h1_away: int

    # Second half (predicted)
    pred_2h_total: float
    pred_2h_margin: float
    pred_2h_home: float
    pred_2h_away: float

    # Final (predicted)
    pred_final_home: float
    pred_final_away: float
    pred_final_total: float
    pred_final_margin: float

    # Intervals (80% CI)
    total_q10: float
    total_q90: float
    margin_q10: float
    margin_q90: float

    # Metadata
    model_name: str
    home_name: str
    away_name: str


class HalftimeModel:
    """
    Halftime prediction model using XGBoost.

    Predicts second half total and margin, then allocates to teams.
    """

    def __init__(self, models_dir: Path = None):
        self.models_dir = models_dir or HALFTIME_MODELS_DIR
        self._loaded = False
        self.total_model = None
        self.margin_model = None
        self.features_total = []
        self.features_margin = []

    def load_models(self) -> bool:
        """Load trained halftime models."""
        if self._loaded:
            return True

        total_path = self.models_dir / DEFAULT_TOTAL_MODEL
        margin_path = self.models_dir / DEFAULT_MARGIN_MODEL

        if not total_path.exists() or not margin_path.exists():
            logger.error(f"Model files not found in {self.models_dir}")
            return False

        try:
            total_obj = joblib.load(total_path)
            margin_obj = joblib.load(margin_path)

            self.features_total = total_obj.get("features", [])
            self.features_margin = margin_obj.get("features", [])
            self.total_model = total_obj.get("model")
            self.margin_model = margin_obj.get("model")

            # Get residual sigmas for intervals
            self.total_sigma = total_obj.get("residual_sigma", 12.0)
            self.margin_sigma = margin_obj.get("residual_sigma", 8.0)

            self._loaded = True
            logger.info(f"Loaded halftime models with {len(self.features_total)} features")
            return True

        except Exception as e:
            logger.error(f"Failed to load halftime models: {e}")
            return False

    def predict(
        self,
        h1_home: int,
        h1_away: int,
        beh: Optional[Dict[str, int]] = None,
        *,
        game_id: str = "",
        home_name: str = "Home",
        away_name: str = "Away",
    ) -> Optional[HalftimePrediction]:
        """
        Predict second half and final game outcomes.

        Args:
            h1_home: First half home score
            h1_away: First half away score
            beh: First half behavior counts (optional)
            game_id: Game ID for tracking
            home_name: Home team name
            away_name: Away team name

        Returns:
            HalftimePrediction or None if models not loaded
        """
        if not self._loaded:
            if not self.load_models():
                return None

        beh = beh or {}

        # Build feature row
        row = {
            "h1_home": h1_home,
            "h1_away": h1_away,
            "h1_total": h1_home + h1_away,
            "h1_margin": h1_home - h1_away,
            "h1_events": beh.get("h1_events", 0),
            "h1_n_2pt": beh.get("h1_n_2pt", 0),
            "h1_n_3pt": beh.get("h1_n_3pt", 0),
            "h1_n_turnover": beh.get("h1_n_turnover", 0),
            "h1_n_rebound": beh.get("h1_n_rebound", 0),
            "h1_n_foul": beh.get("h1_n_foul", 0),
            "h1_n_timeout": beh.get("h1_n_timeout", 0),
            "h1_n_sub": beh.get("h1_n_sub", 0),
        }

        X = pd.DataFrame([row])

        # Predict second half
        pred_2h_total = float(self.total_model.predict(X[self.features_total])[0])
        pred_2h_margin = float(self.margin_model.predict(X[self.features_margin])[0])

        # Allocate to teams
        # H2_home = (total + margin) / 2
        # H2_away = (total - margin) / 2
        pred_2h_home = (pred_2h_total + pred_2h_margin) / 2.0
        pred_2h_away = (pred_2h_total - pred_2h_margin) / 2.0

        # Final predictions
        pred_final_home = h1_home + pred_2h_home
        pred_final_away = h1_away + pred_2h_away
        pred_final_total = pred_final_home + pred_final_away
        pred_final_margin = pred_final_home - pred_final_away

        # 80% confidence intervals
        total_q10 = pred_final_total - Z80 * self.total_sigma
        total_q90 = pred_final_total + Z80 * self.total_sigma
        margin_q10 = pred_final_margin - Z80 * self.margin_sigma
        margin_q90 = pred_final_margin + Z80 * self.margin_sigma

        return HalftimePrediction(
            game_id=game_id,
            h1_home=h1_home,
            h1_away=h1_away,
            pred_2h_total=pred_2h_total,
            pred_2h_margin=pred_2h_margin,
            pred_2h_home=pred_2h_home,
            pred_2h_away=pred_2h_away,
            pred_final_home=pred_final_home,
            pred_final_away=pred_final_away,
            pred_final_total=pred_final_total,
            pred_final_margin=pred_final_margin,
            total_q10=total_q10,
            total_q90=total_q90,
            margin_q10=margin_q10,
            margin_q90=margin_q90,
            model_name="halftime_xgboost",
            home_name=home_name,
            away_name=away_name,
        )

    def predict_from_game_id(
        self,
        game_id: str,
        fetch_odds: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Predict from game ID by fetching live data.

        Args:
            game_id: NBA game ID
            fetch_odds: Whether to fetch odds (not implemented)

        Returns:
            Dict with prediction results
        """
        from src.data.game_data import (
            fetch_box,
            fetch_pbp_df,
            first_half_score,
            behavior_counts_1h,
            get_game_info,
        )

        # Extract game ID if URL provided
        gid = game_id
        if "nba.com" in game_id or len(game_id) > 12:
            from src.data.game_data import extract_game_id
            gid = extract_game_id(game_id)

        # Fetch game data
        try:
            game = fetch_box(gid)
        except Exception as e:
            logger.error(f"Failed to fetch game {gid}: {e}")
            return None

        # Get team info
        info = get_game_info(game)

        # Get first half scores
        h1_home, h1_away = first_half_score(game)
        if h1_home == 0 and h1_away == 0:
            logger.error(f"Could not get first half scores for {gid}")
            return None

        # Get behavior counts
        try:
            pbp = fetch_pbp_df(gid)
            beh = behavior_counts_1h(pbp)
        except Exception as e:
            logger.warning(f"Failed to fetch PBP for {gid}: {e}, using defaults")
            beh = {}

        # Make prediction
        pred = self.predict(
            h1_home=h1_home,
            h1_away=h1_away,
            beh=beh,
            game_id=gid,
            home_name=info.get("home_tricode", "Home"),
            away_name=info.get("away_tricode", "Away"),
        )

        if pred is None:
            return None

        # Convert to dict
        result = {
            "game_id": pred.game_id,
            "home_name": pred.home_name,
            "away_name": pred.away_name,
            "h1_home": pred.h1_home,
            "h1_away": pred.h1_away,
            "pred_2h_total": pred.pred_2h_total,
            "pred_2h_margin": pred.pred_2h_margin,
            "pred_2h_home": pred.pred_2h_home,
            "pred_2h_away": pred.pred_2h_away,
            "pred_final_home": pred.pred_final_home,
            "pred_final_away": pred.pred_final_away,
            "total": pred.pred_final_total,
            "margin": pred.pred_final_margin,
            "total_q10": pred.total_q10,
            "total_q90": pred.total_q90,
            "margin_q10": pred.margin_q10,
            "margin_q90": pred.margin_q90,
            "margin_sd": self.margin_sigma,
            "total_sd": self.total_sigma,
            "model_used": pred.model_name,
            "status": "success",
        }

        # Add REPTAR win probability
        try:
            from src.reptar_integration import enrich_halftime_prediction
            result = enrich_halftime_prediction(result)
            logger.info(f"REPTAR win probability: {result['home_win_prob']:.2%}")
        except Exception as e:
            logger.warning(f"REPTAR enrichment failed: {e}")

        return result


# Global instance
_halftime_model: Optional[HalftimeModel] = None


def get_halftime_model() -> Optional[HalftimeModel]:
    """Get or create halftime model instance."""
    global _halftime_model

    if _halftime_model is None:
        _halftime_model = HalftimeModel()
        _halftime_model.load_models()

    return _halftime_model


def predict_halftime(
    h1_home: int,
    h1_away: int,
    beh: Optional[Dict[str, int]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Simple halftime prediction function.

    Args:
        h1_home: First half home score
        h1_away: First half away score
        beh: First half behavior counts

    Returns:
        Dict with predictions
    """
    model = get_halftime_model()
    if model is None:
        return None

    pred = model.predict(h1_home, h1_away, beh)
    if pred is None:
        return None

    result = {
        "pred_2h_total": pred.pred_2h_total,
        "pred_2h_margin": pred.pred_2h_margin,
        "pred_2h_home": pred.pred_2h_home,
        "pred_2h_away": pred.pred_2h_away,
        "pred_final_home": pred.pred_final_home,
        "pred_final_away": pred.pred_final_away,
        "pred_final_total": pred.pred_final_total,
        "pred_final_margin": pred.pred_final_margin,
    }

    # Add REPTAR win probability
    try:
        from src.reptar_integration import enrich_halftime_prediction
        result = enrich_halftime_prediction(result)
    except Exception:
        pass

    return result


__all__ = [
    "HalftimeModel",
    "HalftimePrediction",
    "get_halftime_model",
    "predict_halftime",
]

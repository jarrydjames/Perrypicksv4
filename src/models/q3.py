"""
Q3 Model - Game-clock aware predictor for in-game predictions.

The Q3 model evaluates predictions at any game state (halftime, end-of-Q3,
or during play) using the same training/calibration methodology as REPTAR.

Key features:
- Two-head architecture (remaining_margin + remaining_total)
- Quantile regression for 80% confidence intervals
- Accepts (period, clock) to evaluate at any game state
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
import joblib
import math
import numpy as np
import logging

from src.modeling.types import TrainedHead, PredictionResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Q3Prediction(PredictionResult):
    """Prediction output from Q3 model."""
    period: int
    clock: str


class Q3Model:
    """
    Q3 model - game-clock aware predictor.

    Uses the same methodology as REPTAR but for any game state.
    """

    MODELS_DIR = Path("models_v3/q3")
    TARGET_TOTAL = "remaining_total"
    TARGET_MARGIN = "remaining_margin"

    def __init__(self):
        self.models_dir = self.MODELS_DIR
        self._loaded = False
        self.total_model = {}
        self.margin_model = {}
        self.features = []
        self.feature_version = "v4_q3"

    def load_models(self) -> bool:
        """Load trained Q3 models if available."""
        if self._loaded:
            return True

        total_path = self.models_dir / "neural_network_q3_total.joblib"
        margin_path = self.models_dir / "neural_network_q3_margin.joblib"

        if not total_path.exists() or not margin_path.exists():
            logger.warning("Q3 models not found")
            return False

        try:
            self.total_model = joblib.load(total_path)
            self.margin_model = joblib.load(margin_path)

            if 'features' in self.total_model:
                self.features = self.total_model['features']

            self._loaded = True
            logger.info(f"Loaded Q3 models with {len(self.features)} features")
            return True

        except Exception as e:
            logger.error(f"Failed to load Q3 models: {e}")
            return False

    def predict(
        self,
        features: Dict[str, float],
        *,
        period: int,
        clock: str,
        game_id: str,
    ) -> Optional[Q3Prediction]:
        """
        Predict at given game state.

        Args:
            features: Dict of feature values
            period: Current quarter (1-4, or OT)
            clock: Clock string (e.g., "PT5M30.00S")
            game_id: Game ID for tracking

        Returns:
            Q3Prediction if models loaded, else None
        """
        if not self._loaded:
            if not self.load_models():
                return None

        # Build feature vector
        feature_names = self.features or list(features.keys())
        X = np.array([[features.get(f, 0.0) for f in feature_names]])

        # Predict total
        total_model = self.total_model.get("model")
        if total_model is not None:
            total_mean = float(total_model.predict(X)[0])
        else:
            total_mean = 55.0  # Default remaining (half game)

        # Predict margin
        margin_model = self.margin_model.get("model")
        if margin_model is not None:
            margin_mean = float(margin_model.predict(X)[0])
        else:
            margin_mean = 0.0

        # Get sigmas
        sigma_total = self.total_model.get("residual_sigma", 8.34)
        sigma_margin = self.margin_model.get("residual_sigma", 6.58)

        # Quantile predictions
        total_q10_model = self.total_model.get("q10_model")
        total_q90_model = self.total_model.get("q90_model")
        margin_q10_model = self.margin_model.get("q10_model")
        margin_q90_model = self.margin_model.get("q90_model")

        if total_q10_model is not None:
            total_q10 = float(total_q10_model.predict(X)[0])
        else:
            total_q10 = total_mean - 8.0

        if total_q90_model is not None:
            total_q90 = float(total_q90_model.predict(X)[0])
        else:
            total_q90 = total_mean + 8.0

        if margin_q10_model is not None:
            margin_q10 = float(margin_q10_model.predict(X)[0])
        else:
            margin_q10 = margin_mean - 1.28 * sigma_margin

        if margin_q90_model is not None:
            margin_q90 = float(margin_q90_model.predict(X)[0])
        else:
            margin_q90 = margin_mean + 1.28 * sigma_margin

        # Calculate home win probability
        z = float(margin_mean) / max(1e-6, float(sigma_margin))
        home_win_prob = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
        home_win_prob = float(np.clip(home_win_prob, 0.01, 0.99))

        return Q3Prediction(
            game_id=game_id,
            period=period,
            clock=clock,
            home_win_prob=home_win_prob,
            margin_mean=margin_mean,
            margin_sd=sigma_margin,
            total_mean=total_mean,
            total_sd=sigma_total,
            margin_q10=margin_q10,
            margin_q90=margin_q90,
            total_q10=total_q10,
            total_q90=total_q90,
            model_name="q3_neural_network",
            model_version="1.0.0",
            feature_version=self.feature_version,
        )


# Global instance
_q3_model: Optional[Q3Model] = None


def get_q3_model() -> Optional[Q3Model]:
    """Get or create Q3 model instance."""
    global _q3_model

    if _q3_model is None:
        _q3_model = Q3Model()
        _q3_model.load_models()

    return _q3_model


__all__ = [
    "Q3Model",
    "Q3Prediction",
    "get_q3_model",
]

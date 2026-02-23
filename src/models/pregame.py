"""
Pregame Model - Uses champion models with rate-based features.

The pregame model predicts game outcomes before tip-off using:
- Team ratings and efficiency metrics
- Recent form (last 10 games)
- Head-to-head history
- Schedule features (rest, B2B)

Champion Models (from comprehensive 7-model evaluation):
- Total: Neural Network (R2: 0.592, MAE: 9.578)
- Margin: Neural Network (R2: 0.945, MAE: 2.954)
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
import joblib
import math
import numpy as np
import logging

from src.modeling.base import BaseTwoHeadModel, TwoHeadFitResult
from src.modeling.types import TrainedHead, PredictionResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PregamePrediction(PredictionResult):
    """Prediction output from pregame model."""
    pass


class PregameModel:
    """
    Pregame model using champion neural network models.

    Features rate-based efficiency metrics that are leakage-safe.
    """

    MODELS_DIR = Path("models_v3/pregame")
    TARGET_TOTAL = "total"
    TARGET_MARGIN = "margin"

    def __init__(self):
        self.models_dir = self.MODELS_DIR
        self._loaded = False
        self.total_model = {}
        self.margin_model = {}
        self.features = []
        self.feature_version = "v4_pregame"

    def load_models(self) -> bool:
        """Load trained pregame models if available."""
        if self._loaded:
            return True

        # Try neural network first (champion)
        total_path = self.models_dir / "neural_network_total.joblib"
        margin_path = self.models_dir / "neural_network_margin.joblib"

        # Fallbacks
        if not total_path.exists():
            total_path = self.models_dir / "randomforest_total.joblib"
        if not total_path.exists():
            total_path = self.models_dir / "gbt_total.joblib"

        if not margin_path.exists():
            margin_path = self.models_dir / "randomforest_margin.joblib"
        if not margin_path.exists():
            margin_path = self.models_dir / "gbt_margin.joblib"

        if not total_path.exists() or not margin_path.exists():
            logger.warning("Pregame models not found")
            return False

        try:
            self.total_model = joblib.load(total_path)
            self.margin_model = joblib.load(margin_path)

            # Get feature list
            if 'features' in self.total_model:
                self.features = self.total_model['features']
            elif 'features' in self.margin_model:
                self.features = self.margin_model['features']

            self._loaded = True
            logger.info(f"Loaded pregame models with {len(self.features)} features")
            return True

        except Exception as e:
            logger.error(f"Failed to load pregame models: {e}")
            return False

    def predict(
        self,
        features: Dict[str, float],
        *,
        game_id: str,
    ) -> Optional[PregamePrediction]:
        """
        Predict game outcome.

        Args:
            features: Dict of feature values
            game_id: Game ID for tracking

        Returns:
            PregamePrediction if models loaded, else None
        """
        if not self._loaded:
            if not self.load_models():
                return None

        # Build feature vector in correct order
        feature_values = [features.get(f, 0.0) for f in self.features]
        X = np.array([feature_values])

        # Predict total
        total_model = self.total_model.get("model")
        if total_model is not None:
            total_mean = float(total_model.predict(X)[0])
        else:
            total_mean = 215.0  # NBA average

        # Predict margin
        margin_model = self.margin_model.get("model")
        if margin_model is not None:
            margin_mean = float(margin_model.predict(X)[0])
        else:
            margin_mean = 0.0

        # Get sigmas
        sigma_total = self.total_model.get("residual_sigma", 15.6)
        sigma_margin = self.margin_model.get("residual_sigma", 11.2)

        # 80% confidence intervals (using 1.28 z-score)
        total_q10 = total_mean - 1.28 * sigma_total
        total_q90 = total_mean + 1.28 * sigma_total
        margin_q10 = margin_mean - 1.28 * sigma_margin
        margin_q90 = margin_mean + 1.28 * sigma_margin

        # Calculate home win probability
        # P(home wins) = P(margin > 0) = 1 - Phi(-margin_mean / margin_sd)
        z = float(margin_mean) / max(1e-6, float(sigma_margin))
        home_win_prob = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
        home_win_prob = float(np.clip(home_win_prob, 0.01, 0.99))

        return PregamePrediction(
            game_id=game_id,
            home_win_prob=home_win_prob,
            margin_mean=margin_mean,
            margin_sd=sigma_margin,
            total_mean=total_mean,
            total_sd=sigma_total,
            margin_q10=margin_q10,
            margin_q90=margin_q90,
            total_q10=total_q10,
            total_q90=total_q90,
            model_name="pregame_neural_network",
            model_version="1.0.0",
            feature_version=self.feature_version,
        )


# Global instance
_pregame_model: Optional[PregameModel] = None


def get_pregame_model() -> Optional[PregameModel]:
    """Get or create pregame model instance."""
    global _pregame_model

    if _pregame_model is None:
        _pregame_model = PregameModel()
        _pregame_model.load_models()

    return _pregame_model


__all__ = [
    "PregameModel",
    "PregamePrediction",
    "get_pregame_model",
]

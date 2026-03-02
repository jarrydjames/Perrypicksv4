"""
Pregame Model - Uses champion models with rate-based features.

The pregame model predicts game outcomes before tip-off using:
- Team ratings and efficiency metrics
- Recent form (last 10 games)
- Head-to-head history
- Schedule features (rest, B2B)

Champion Models:
- Primary (v5/Maximus): CatBoost deploy models (`Maximus/models/catboost_{total,margin}.cbm`)
- Fallback (legacy): joblib neural_network_* in `models_v3/pregame/`
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
import joblib
import math
import numpy as np
import logging
from pathlib import Path

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
    MAXIMUS_MODELS_DIR = Path("Maximus/models")
    TARGET_TOTAL = "total"
    TARGET_MARGIN = "margin"

    def __init__(self):
        self.models_dir = self.MODELS_DIR
        self._loaded = False
        self.total_model = {}
        self.margin_model = {}
        self.features = []
        self._backend: str = "unknown"  # catboost|maximus_legacy_joblib
        self.feature_version = "v4_pregame"

    def load_models(self) -> bool:
        """Load trained pregame models.

        Prefers v5/Maximus CatBoost deploy models if present.
        """
        if self._loaded:
            return True

        # --- Preferred: Maximus CatBoost deploy models ---
        cb_total = self.MAXIMUS_MODELS_DIR / "catboost_total.cbm"
        cb_margin = self.MAXIMUS_MODELS_DIR / "catboost_margin.cbm"

        if cb_total.exists() and cb_margin.exists():
            try:
                from catboost import CatBoostRegressor
                from src.data.maximus_features import maximus_feature_columns

                self.features = maximus_feature_columns()  # ordered (54)
                self.total_model = CatBoostRegressor()
                self.total_model.load_model(str(cb_total))
                self.margin_model = CatBoostRegressor()
                self.margin_model.load_model(str(cb_margin))

                self._backend = "catboost"
                self._loaded = True
                logger.info(f"Loaded MAXIMUS CatBoost models with {len(self.features)} features")
                return True
            except Exception as e:
                logger.error(f"Failed to load MAXIMUS CatBoost models: {e}. Falling back to joblib models.")

        # --- Fallback: legacy joblib models ---
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

        if self._backend == "catboost":
            # CatBoostRegressor API
            try:
                total_mean = float(self.total_model.predict(X)[0])
            except Exception:
                total_mean = 215.0

            try:
                margin_mean = float(self.margin_model.predict(X)[0])
            except Exception:
                margin_mean = 0.0

            # No baked sigma in cbm artifact. Use conservative defaults.
            sigma_total = 15.6
            sigma_margin = 11.2
        else:
            # Legacy joblib dict API
            total_model = self.total_model.get("model")
            if total_model is not None:
                total_mean = float(total_model.predict(X)[0])
            else:
                total_mean = 215.0  # NBA average

            margin_model = self.margin_model.get("model")
            if margin_model is not None:
                margin_mean = float(margin_model.predict(X)[0])
            else:
                margin_mean = 0.0

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
            model_name=("maximus_catboost" if self._backend == "catboost" else "pregame_neural_network"),
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

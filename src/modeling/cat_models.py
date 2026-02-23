"""CatBoost two-head model for REPTAR halftime predictions."""

from __future__ import annotations

from typing import List, Tuple

import numpy as np

from src.modeling.base import BaseTwoHeadModel, TwoHeadFitResult
from src.modeling.types import TrainedHead
from src.modeling.uncertainty import sigma_from_residuals


class CatBoostTwoHeadModel(BaseTwoHeadModel):
    """
    CatBoost two-head regressor for predicting total and margin.

    This model uses separate CatBoost regressors for H2 total and H2 margin,
    providing the accuracy needed for REPTAR's 75% win prediction rate.

    Note: This is a backtest/training model that requires catboost package.
    The runtime prediction uses pre-trained model artifacts.
    """

    name = "catboost"
    version = "1"

    def __init__(
        self,
        *,
        iterations: int = 2500,
        learning_rate: float = 0.03,
        depth: int = 6,
        l2_leaf_reg: float = 3.0,
        subsample: float = 0.8,
        feature_version: str = "v1",
        random_seed: int = 0,
    ):
        super().__init__(feature_version=feature_version)
        self.params = {
            "iterations": int(iterations),
            "learning_rate": float(learning_rate),
            "depth": int(depth),
            "l2_leaf_reg": float(l2_leaf_reg),
            "subsample": float(subsample),
            "loss_function": "RMSE",
            "random_seed": int(random_seed),
            "verbose": False,
        }
        self._fit: TwoHeadFitResult | None = None

    def fit(
        self,
        X: np.ndarray,
        feature_names: List[str],
        y_total: np.ndarray,
        y_margin: np.ndarray,
    ) -> "CatBoostTwoHeadModel":
        """Fit both heads on training data."""
        try:
            from catboost import CatBoostRegressor  # type: ignore
        except Exception as e:
            raise RuntimeError(
                "catboost is not installed. Install with: pip install catboost"
            ) from e

        # Train total model
        mt = CatBoostRegressor(**self.params)
        mt.fit(X, y_total)

        # Train margin model
        mm = CatBoostRegressor(**self.params)
        mm.fit(X, y_margin)

        # Calculate residual sigmas
        res_t = y_total - mt.predict(X)
        res_m = y_margin - mm.predict(X)

        self._fit = TwoHeadFitResult(
            total=TrainedHead(
                features=list(feature_names),
                model=mt,
                residual_sigma=sigma_from_residuals(res_t),
            ),
            margin=TrainedHead(
                features=list(feature_names),
                model=mm,
                residual_sigma=sigma_from_residuals(res_m),
            ),
        )
        return self

    def predict_heads(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Return (mu_total, mu_margin) predictions."""
        if not self._fit:
            raise RuntimeError("Model not fit")
        return (
            self._fit.total.model.predict(X),
            self._fit.margin.model.predict(X),
        )

    def trained_heads(self) -> TwoHeadFitResult:
        """Return trained heads with residual sigmas."""
        if not self._fit:
            raise RuntimeError("Model not fit")
        return self._fit


__all__ = ['CatBoostTwoHeadModel']

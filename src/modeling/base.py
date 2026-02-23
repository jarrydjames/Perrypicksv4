"""Base model architecture for two-head prediction (total + margin)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import numpy as np

from src.modeling.types import TrainedHead


@dataclass
class TwoHeadFitResult:
    """Result from fitting a two-head model."""
    total: TrainedHead
    margin: TrainedHead


class BaseTwoHeadModel(ABC):
    """
    Abstract base for models predicting TOTAL and MARGIN separately.

    This architecture allows:
    - Independent optimization for each target
    - Different feature importance per target
    - Proper uncertainty quantification

    Implementations must:
    - Store feature_version
    - Train two heads (total, margin)
    - Estimate residual sigmas per head
    """

    name: str
    version: str
    feature_version: str

    def __init__(self, *, feature_version: str = "v1"):
        self.feature_version = feature_version

    @abstractmethod
    def fit(
        self,
        X: np.ndarray,
        feature_names: List[str],
        y_total: np.ndarray,
        y_margin: np.ndarray,
    ) -> "BaseTwoHeadModel":
        """Fit both heads on training data."""
        raise NotImplementedError

    @abstractmethod
    def predict_heads(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Return (mu_total, mu_margin) predictions."""
        raise NotImplementedError

    @abstractmethod
    def trained_heads(self) -> TwoHeadFitResult:
        """Return trained heads with residual sigmas."""
        raise NotImplementedError

    def diagnostics(self) -> Dict[str, Any]:
        """Return model diagnostics."""
        return {
            "model": self.name,
            "version": self.version,
            "feature_version": self.feature_version,
        }

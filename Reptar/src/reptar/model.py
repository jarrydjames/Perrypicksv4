from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import joblib
import numpy as np

from reptar.paths import artifacts_dir, models_dir


@dataclass(frozen=True)
class ReptarArtifacts:
    total_path: Path
    margin_path: Path
    feature_names: List[str]


class ReptarModel:
    """Load + run REPTAR CatBoost halftime models.

    The production artifacts are `joblib` objects containing:
    - model: a CatBoost model object
    - features: ordered list of feature column names
    """

    def __init__(
        self,
        *,
        total_model_path: Path | None = None,
        margin_model_path: Path | None = None,
    ):
        self.total_model_path = total_model_path or (models_dir() / "catboost_h2_total.joblib")
        self.margin_model_path = margin_model_path or (models_dir() / "catboost_h2_margin.joblib")

        self._total_model: Any | None = None
        self._margin_model: Any | None = None
        self._features: List[str] = []
        self._loaded = False

    @property
    def features(self) -> List[str]:
        return list(self._features)

    def load(self) -> None:
        if self._loaded:
            return

        if not self.total_model_path.exists():
            raise FileNotFoundError(f"Missing total model: {self.total_model_path}")
        if not self.margin_model_path.exists():
            raise FileNotFoundError(f"Missing margin model: {self.margin_model_path}")

        total_obj = joblib.load(self.total_model_path)
        margin_obj = joblib.load(self.margin_model_path)

        self._total_model = total_obj["model"]
        self._margin_model = margin_obj["model"]

        total_feats = list(total_obj.get("features") or [])
        margin_feats = list(margin_obj.get("features") or [])
        if total_feats != margin_feats:
            raise ValueError("Total/margin feature schemas differ — refusing to continue")

        self._features = total_feats
        self._loaded = True

    def predict(self, features: Dict[str, float]) -> Tuple[float, float]:
        """Return (pred_total, pred_margin) for final game."""
        self.load()

        X = np.asarray([[float(features.get(f, 0.0)) for f in self._features]], dtype=float)
        total = float(self._total_model.predict(X)[0])
        margin = float(self._margin_model.predict(X)[0])
        return total, margin

    def export_feature_schema(self) -> Path:
        """Write artifacts/FEATURE_SCHEMA.json (ordered list)."""
        self.load()
        out = artifacts_dir() / "FEATURE_SCHEMA.json"
        out.write_text(json.dumps({"features": self._features}, indent=2), encoding="utf-8")
        return out


__all__ = ["ReptarModel", "ReptarArtifacts"]

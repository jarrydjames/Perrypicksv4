"""Validate deployed Maximus models + feature schema.

This is a small sanity script for future-you.

Checks:
- features.parquet defines 54 ordered feature columns
- CatBoost deploy models exist
- CatBoost models can predict on a sample row

Usage:
  python Maximus/scripts/10_validate_deploy_models.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def main() -> int:
    feats_path = Path("Maximus/data/processed/features.parquet")
    cb_total = Path("Maximus/models/catboost_total.cbm")
    cb_margin = Path("Maximus/models/catboost_margin.cbm")

    if not feats_path.exists():
        raise FileNotFoundError(feats_path)
    if not cb_total.exists():
        raise FileNotFoundError(cb_total)
    if not cb_margin.exists():
        raise FileNotFoundError(cb_margin)

    feats = pd.read_parquet(feats_path)
    feature_cols = [c for c in feats.columns if c != "game_id"]
    if len(feature_cols) != 54:
        raise ValueError(f"Expected 54 features, got {len(feature_cols)}")

    from catboost import CatBoostRegressor

    m_total = CatBoostRegressor()
    m_total.load_model(str(cb_total))
    m_margin = CatBoostRegressor()
    m_margin.load_model(str(cb_margin))

    X = feats[feature_cols].head(1).to_numpy(dtype=float)
    y_t = float(m_total.predict(X)[0])
    y_m = float(m_margin.predict(X)[0])

    print("ok")
    print("n_features", len(feature_cols))
    print("sample_pred_total", y_t)
    print("sample_pred_margin", y_m)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

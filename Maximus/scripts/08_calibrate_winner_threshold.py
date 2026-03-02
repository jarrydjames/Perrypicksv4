"""Calibrate winner decision threshold on DEV OOF predictions.

This is Protocol V2 material:
- Use ONLY dev walk-forward OOF predictions.
- Select threshold maximizing win_acc subject to coverage >= min_coverage.

Outputs:
- Maximus/artifacts/WINNER_THRESHOLD_CALIBRATION.json
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from Maximus.src.eval.calibration import calibrate_margin_threshold_by_folds
from Maximus.src.eval.splits import load_splits
from Maximus.src.eval.walkforward import walkforward_oof_single_target
from Maximus.src.paths import artifacts_dir


def main() -> int:
    # Use pre-built processed matrix to avoid recomputing features.
    matrix_path = Path("Maximus/data/processed/model_matrix.parquet")
    if not matrix_path.exists():
        raise FileNotFoundError("Missing model_matrix.parquet. Run 02_build_features first.")

    import pandas as pd

    df = pd.read_parquet(matrix_path)

    # Use the exact feature columns that were produced by the feature pipeline
    feats_path = Path("Maximus/data/processed/features.parquet")
    if not feats_path.exists():
        raise FileNotFoundError("Missing features.parquet. Run 02_build_features first.")
    feats = pd.read_parquet(feats_path)
    feature_cols = [c for c in feats.columns if c != "game_id"]

    splits = load_splits(artifacts_dir() / "SPLITS_V2.json")
    dev_idx = np.asarray(splits.dev_indices, dtype=int)

    X_dev = df.iloc[dev_idx][feature_cols].to_numpy(dtype=float)
    y_margin_dev = df.iloc[dev_idx]["margin"].to_numpy(dtype=float)

    # Use tuned params from best CatBoost margin study (already computed)
    optuna_path = artifacts_dir() / "OPTUNA_catboost_margin.json"
    best_params = json.loads(optuna_path.read_text(encoding="utf-8"))["best"]["params"]

    res = walkforward_oof_single_target(
        X=X_dev,
        y=y_margin_dev,
        cv_folds=splits.cv_folds,
        model_type="catboost",
        target="margin",
        seed=42,
        params=best_params,
    )

    oof_pred = res["oof_pred"]
    mask = ~np.isnan(oof_pred)

    # Candidate thresholds
    candidates = [0, 0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 7, 10]

    best = calibrate_margin_threshold_by_folds(
        y_true_margin=y_margin_dev,
        pred_margin=oof_pred,
        cv_folds=splits.cv_folds,
        candidate_thresholds=[float(x) for x in candidates],
        min_coverage=0.70,
        use_last_k_folds=10,
    )

    out = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": "catboost",
        "target": "margin",
        "seed": 42,
        "min_coverage": 0.70,
        "candidates": candidates,
        "method": "fold_robust_last_k",
        "use_last_k_folds": 10,
        "best": {"threshold": best.threshold, "win_acc": best.win_acc, "coverage": best.coverage},
    }

    out_path = artifacts_dir() / "WINNER_THRESHOLD_CALIBRATION.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

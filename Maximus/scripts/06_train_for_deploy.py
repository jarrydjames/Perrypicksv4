"""Train final deployable models after a GO decision.

This script is intentionally separate from evaluation.

Rules:
- Requires artifacts/GO_NO_GO_V2.json decision == "GO".
- Trains on ALL data EXCEPT the locked Future TEST window defined in SPLITS_V2.json.
  (i.e., includes DEV + holdout + future_shadow)

Outputs:
- Maximus/models/
  - catboost_margin.cbm
  - catboost_total.cbm
  - xgboost_margin.json
  - xgboost_total.json
- Maximus/artifacts/DEPLOY_MODELS_MANIFEST.json
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from Maximus.src.eval.splits import load_splits
from Maximus.src.paths import artifacts_dir
from Maximus.src.utils_hashing import sha256_file


def _load_best_params(model_type: str, target: str) -> dict:
    p = artifacts_dir() / f"OPTUNA_{model_type}_{target}.json"
    if not p.exists():
        raise FileNotFoundError(f"Missing tuning artifact: {p}")
    payload = json.loads(p.read_text(encoding="utf-8"))
    return payload["best"]["params"]


def main() -> int:
    go_path = artifacts_dir() / "GO_NO_GO_V2.json"
    if not go_path.exists():
        raise FileNotFoundError("Missing GO_NO_GO_V2.json. Run 05_train_and_eval_v2 first.")

    go = json.loads(go_path.read_text(encoding="utf-8"))
    if go.get("decision") != "GO":
        raise RuntimeError(f"Decision is not GO (got {go.get('decision')}). Refusing to train deploy models.")

    # Use pre-built processed matrix to avoid feature drift between eval and deploy.
    from pathlib import Path
    import pandas as pd

    matrix_path = Path("Maximus/data/processed/model_matrix.parquet")
    feats_path = Path("Maximus/data/processed/features.parquet")
    if not matrix_path.exists() or not feats_path.exists():
        raise FileNotFoundError("Missing processed data. Run 02_build_features first.")

    df = pd.read_parquet(matrix_path)
    feats = pd.read_parquet(feats_path)
    feature_cols = [c for c in feats.columns if c != "game_id"]

    splits = load_splits(artifacts_dir() / "SPLITS_V2.json")
    locked_test = set(int(i) for i in splits.future_indices)

    train_idx = [i for i in range(len(df)) if i not in locked_test]
    train_df = df.iloc[train_idx].reset_index(drop=True)

    X = train_df[feature_cols].to_numpy(dtype=float)
    y_margin = train_df["margin"].to_numpy(dtype=float)
    y_total = train_df["total"].to_numpy(dtype=float)

    out_dir = Path("Maximus/models")
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "train_regime": "all_except_locked_future_test",
        "locked_future_test_size": int(len(locked_test)),
        "n_games": int(len(train_df)),
        "models": {},
    }

    # CatBoost
    import catboost as cb

    for target, y in [("margin", y_margin), ("total", y_total)]:
        params = _load_best_params("catboost", target)
        base = {
            "loss_function": "MAE",
            "random_seed": 42,
            "verbose": False,
            "allow_writing_files": False,
        }
        base.update(params)
        model = cb.CatBoostRegressor(**base).fit(X, y)
        path = out_dir / f"catboost_{target}.cbm"
        model.save_model(str(path))
        manifest["models"][f"catboost_{target}"] = {
            "path": str(path),
            "sha256": sha256_file(path),
            "params": base,
        }

    # XGBoost
    import xgboost as xgb

    for target, y in [("margin", y_margin), ("total", y_total)]:
        params = _load_best_params("xgboost", target)
        base = {
            "objective": "reg:squarederror",
            "random_state": 42,
            "n_jobs": -1,
        }
        base.update(params)
        model = xgb.XGBRegressor(**base).fit(X, y)
        path = out_dir / f"xgboost_{target}.json"
        model.save_model(str(path))
        manifest["models"][f"xgboost_{target}"] = {
            "path": str(path),
            "sha256": sha256_file(path),
            "params": base,
        }

    out_manifest = artifacts_dir() / "DEPLOY_MODELS_MANIFEST.json"
    out_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Wrote deploy models to: {out_dir}")
    print(f"Wrote manifest: {out_manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

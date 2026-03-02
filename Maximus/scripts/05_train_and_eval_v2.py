"""Train and evaluate Maximus models under Protocol V2.

Protocol V2 changes:
- Winner metric uses a confidence-gated policy (abstain) with threshold calibrated on DEV OOF.
- Red-team suite uses label-shift stress test instead of naive time reversal.

Outputs:
- Maximus/artifacts/GO_NO_GO_V2.json
- Maximus/reports/EVALUATION_REPORT_V2.md

NOTE:
This script is meant to be run on a NEW locked holdout window after protocol changes.
It does not delete/overwrite V1 outputs.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from Maximus.src.eval.baselines import estimate_hca_from_dev, predict_margin_constant
from Maximus.src.eval.bootstrap import paired_bootstrap_ci
from Maximus.src.eval.calibration import ThresholdCalibrationResult
from Maximus.src.eval.decision import DecisionPolicy, win_acc_with_abstain
from Maximus.src.eval.metrics import regression_metrics
from Maximus.src.eval.red_team import ablation_test, label_shift_stress_test, permutation_test
from Maximus.src.eval.splits import load_splits
from Maximus.src.models.trainers import ModelConfig, train_model
from Maximus.src.paths import artifacts_dir, reports_dir


def main() -> int:
    artifacts_dir().mkdir(parents=True, exist_ok=True)
    reports_dir().mkdir(parents=True, exist_ok=True)

    # load processed matrix (features already built)
    matrix_path = Path("Maximus/data/processed/model_matrix.parquet")
    feats_path = Path("Maximus/data/processed/features.parquet")
    if not matrix_path.exists() or not feats_path.exists():
        raise FileNotFoundError("Missing processed data. Run 02_build_features.")

    df = pd.read_parquet(matrix_path)
    feats = pd.read_parquet(feats_path)
    feature_cols = [c for c in feats.columns if c != "game_id"]

    splits = load_splits(artifacts_dir() / "SPLITS_V2.json")
    dev_idx = np.asarray(splits.dev_indices, dtype=int)
    hold_idx = np.asarray(splits.holdout_indices, dtype=int)
    fut_idx = np.asarray(splits.future_indices, dtype=int)
    shadow_idx = np.asarray(getattr(splits, "future_shadow_indices", []), dtype=int)

    X = df[feature_cols].to_numpy(dtype=float)
    y_margin = df["margin"].to_numpy(dtype=float)

    X_dev, X_hold, X_fut = X[dev_idx], X[hold_idx], X[fut_idx]
    y_dev, y_hold, y_fut = y_margin[dev_idx], y_margin[hold_idx], y_margin[fut_idx]

    X_shadow = X[shadow_idx] if len(shadow_idx) else None
    y_shadow = y_margin[shadow_idx] if len(shadow_idx) else None

    # Load calibrated threshold (or fail)
    cal_path = artifacts_dir() / "WINNER_THRESHOLD_CALIBRATION.json"
    if not cal_path.exists():
        raise FileNotFoundError("Missing WINNER_THRESHOLD_CALIBRATION.json. Run 08_calibrate_winner_threshold.")

    cal = json.loads(cal_path.read_text(encoding="utf-8"))
    threshold = float(cal["best"]["threshold"])
    min_cov = float(cal["min_coverage"])
    policy = DecisionPolicy(threshold=threshold)

    # Train primary model on DEV, evaluate holdout + future
    params = json.loads((artifacts_dir() / "OPTUNA_catboost_margin.json").read_text(encoding="utf-8"))["best"]["params"]
    cfg = ModelConfig(model_type="catboost", target="margin", seed=42, params=params)

    model = train_model(X_dev, y_dev, cfg)

    pred_hold = model.predict(X_hold)
    pred_fut = model.predict(X_fut)
    pred_shadow = model.predict(X_shadow) if X_shadow is not None else None

    met_hold = regression_metrics(y_hold, pred_hold)
    met_fut = regression_metrics(y_fut, pred_fut)
    met_shadow = regression_metrics(y_shadow, pred_shadow) if pred_shadow is not None else None

    # Baseline: constant HCA from DEV
    hca = estimate_hca_from_dev(y_dev)
    base_hold = predict_margin_constant(len(hold_idx), hca)
    base_fut = predict_margin_constant(len(fut_idx), hca)

    base_hold_met = regression_metrics(y_hold, base_hold)

    # Winner policy metrics
    hold_policy = win_acc_with_abstain(y_hold, pred_hold, policy)
    fut_policy = win_acc_with_abstain(y_fut, pred_fut, policy)
    shadow_policy = win_acc_with_abstain(y_shadow, pred_shadow, policy) if pred_shadow is not None else None

    fut_drop_pp = (hold_policy["win_acc"] - fut_policy["win_acc"]) * 100.0

    # Bootstrap on holdout MAE (model vs baseline)
    boot = paired_bootstrap_ci(y_hold, pred_hold, base_hold, n_boot=10_000, seed=123)

    # Red team (dev only)
    cv_folds = splits.cv_folds
    rt_perm = permutation_test(X_dev, y_dev, cv_folds=cv_folds, model_type="catboost", seed=999, n_reps=10)

    core_cols = [c for c in feature_cols if c.startswith("home_elo") or c.startswith("away_elo") or c.startswith("elo_")]
    core_cols += [c for c in feature_cols if c.startswith("rest_") or c.startswith("b2b_") or c.startswith("games_last")]
    core_cols += [c for c in feature_cols if "sos" in c]
    core_cols = sorted(set(core_cols))
    X_dev_core = df.iloc[dev_idx][core_cols].to_numpy(dtype=float)

    rt_abl = ablation_test(X_full=X_dev, X_core=X_dev_core, y=y_dev, cv_folds=cv_folds, model_type="catboost", seed=999)
    rt_shift = label_shift_stress_test(X_dev, y_dev, cv_folds=cv_folds, model_type="catboost", seed=999, shift=3.0)

    red_pass = bool(rt_perm.passed and rt_abl.passed and rt_shift.passed)

    gates = {
        "holdout_mae_improvement": {
            "value": float(base_hold_met.mae - met_hold.mae),
            "required": 0.5,
            "pass": bool((base_hold_met.mae - met_hold.mae) >= 0.5),
        },
        "bootstrap_mae_ci": {"ci95": boot["mae_delta"]["ci95"], "pass": bool(boot["mae_delta"]["pass"])},
        "winner_policy_holdout_win_acc": {
            "value": float(hold_policy["win_acc"]),
            "required": 0.70,
            "pass": bool(hold_policy["win_acc"] >= 0.70),
        },
        "winner_policy_coverage_holdout": {
            "value": float(hold_policy["coverage"]),
            "required": min_cov,
            "pass": bool(hold_policy["coverage"] >= min_cov),
        },
        "winner_policy_future_drop_pp": {
            "value": float(fut_drop_pp),
            "required": 5.0,
            "pass": bool(fut_drop_pp <= 5.0),
        },
        "winner_policy_coverage_future": {
            "value": float(fut_policy["coverage"]),
            "required": min_cov,
            "pass": bool(fut_policy["coverage"] >= min_cov),
        },
        "red_team": {
            "permutation": {"pass": rt_perm.passed, "details": rt_perm.details},
            "ablation": {"pass": rt_abl.passed, "details": rt_abl.details},
            "label_shift": {"pass": rt_shift.passed, "details": rt_shift.details},
            "pass": red_pass,
        },
    }

    decision = "GO" if all(v["pass"] for v in gates.values()) else "NO-GO"

    out = {
        "project": "Maximus",
        "protocol": "V2",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "policy": {"threshold": threshold, "min_coverage": min_cov},
        "summary": {
            "holdout": {
                "mae": met_hold.mae,
                "baseline_mae": base_hold_met.mae,
                "policy_win_acc": hold_policy["win_acc"],
                "policy_coverage": hold_policy["coverage"],
            },
            "future": {
                "mae": met_fut.mae,
                "baseline_mae": regression_metrics(y_fut, base_fut).mae,
                "policy_win_acc": fut_policy["win_acc"],
                "policy_coverage": fut_policy["coverage"],
            },
            "future_shadow": (
                {
                    "mae": met_shadow.mae,
                    "baseline_mae": regression_metrics(y_shadow, predict_margin_constant(len(shadow_idx), hca)).mae,
                    "policy_win_acc": shadow_policy["win_acc"],
                    "policy_coverage": shadow_policy["coverage"],
                }
                if met_shadow is not None
                else None
            ),
        },
        "gates": gates,
    }

    (artifacts_dir() / "GO_NO_GO_V2.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    report_lines = [
        "# Evaluation Report (Maximus) — V2",
        "",
        f"Generated at: {out['timestamp']}",
        "",
        f"## Policy\n- threshold: {threshold}\n- min_coverage: {min_cov}",
        "",
        "## Holdout",
        f"- MAE: {met_hold.mae:.4f} (baseline {base_hold_met.mae:.4f})",
        f"- Policy win_acc: {hold_policy['win_acc']:.4f}",
        f"- Policy coverage: {hold_policy['coverage']:.4f}",
        "",
        "## Future",
        f"- MAE: {met_fut.mae:.4f}",
        f"- Policy win_acc: {fut_policy['win_acc']:.4f}",
        f"- Policy coverage: {fut_policy['coverage']:.4f}",
        "",
        "## Gates",
        "```",
        json.dumps(gates, indent=2),
        "```",
        "",
        f"## Decision\n{decision}",
    ]
    (reports_dir() / "EVALUATION_REPORT_V2.md").write_text("\n".join(report_lines), encoding="utf-8")

    print(f"Wrote: {artifacts_dir() / 'GO_NO_GO_V2.json'}")
    print(f"Decision: {decision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Train and evaluate Maximus models with locked protocol.

Generates REQUIRED artifacts:
- RUN_MANIFEST.json
- MODEL_TRAINING_REPORT.md
- EVALUATION_REPORT.md
- GO_NO_GO.json
- HOLDOUT_PREDICTIONS.csv
- FUTURE_PREDICTIONS.csv
- SEED_SWEEP_SUMMARY.csv
- RED_TEAM_REPORT.md
- DRIFT_REPORT.md

IMPORTANT:
- This script must not be re-run to "try again" after seeing holdout.
- If gates fail: writes NO-GO and stops.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from Maximus.src.data.load_raw import load_historical_games
from Maximus.src.eval.baselines import (
    estimate_hca_from_dev,
    estimate_total_mean_from_dev,
    predict_margin_constant,
    predict_margin_zero,
    predict_total_constant,
)
from Maximus.src.eval.bootstrap import paired_bootstrap_ci
from Maximus.src.eval.drift import feature_drift_summary, fold_trend_test
from Maximus.src.eval.metrics import regression_metrics, winner_metrics_from_margin
from Maximus.src.eval.red_team import ablation_test, permutation_test, time_reversal_test
from Maximus.src.eval.splits import load_splits
from Maximus.src.eval.walkforward import walkforward_oof_predictions
from Maximus.src.features.build_features import build_pregame_features
from Maximus.src.models.optuna_tuning import TuningSpec, tune_model_params
from Maximus.src.models.trainers import ModelConfig, train_model
from Maximus.src.paths import artifacts_dir, reports_dir
from Maximus.src.utils_hashing import sha256_file


SUCCESS_CRITERIA = {
    "holdout_mae_improvement_min": 0.5,
    "holdout_win_acc_improvement_min_pp": 2.0,
    "bootstrap_mae_ci_upper_lt_0": True,
    "bootstrap_win_ci_lower_gt_0": True,
    "repeatability_std_mae_max": 0.25,
    "repeatability_std_win_acc_pp_max": 1.0,
    # future block stress gates
    "future_mae_max_multiplier": 1.20,
    "future_win_acc_drop_max_pp": 5.0,
}


def _seed_sweep(
    X_dev: np.ndarray,
    y_margin_dev: np.ndarray,
    y_total_dev: np.ndarray,
    cv_folds: list[dict],
    model_type: str,
    seeds: list[int],
    params_margin: dict,
    params_total: dict,
) -> pd.DataFrame:
    rows = []
    for seed in seeds:
        res = walkforward_oof_predictions(
            X_dev,
            y_margin_dev,
            y_total_dev,
            cv_folds=cv_folds,
            model_type=model_type,
            seed=seed,
            params_margin=params_margin,
            params_total=params_total,
        )
        rows.append(
            {
                "model": model_type,
                "seed": seed,
                "margin_mae": res["margin"]["global"]["mae"],
                "margin_win_acc": res["margin"]["global"]["win_acc"],
                "total_mae": res["total"]["global"]["mae"],
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    artifacts_dir().mkdir(parents=True, exist_ok=True)
    reports_dir().mkdir(parents=True, exist_ok=True)

    games = load_historical_games()
    feats, _ = build_pregame_features(games)

    split_path = artifacts_dir() / "SPLITS.json"
    if not split_path.exists():
        raise FileNotFoundError("Missing SPLITS.json. Run scripts/04_make_splits.py")
    splits = load_splits(split_path)

    # git commit hash (best-effort)
    try:
        import subprocess

        git_sha = (
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(Path(__file__).resolve().parents[2]))
            .decode("utf-8")
            .strip()
        )
    except Exception:
        git_sha = "UNKNOWN"

    # Build model matrix
    df = games.merge(feats, on="game_id", how="left")

    id_cols = ["game_id", "game_date", "season", "home_tri", "away_tri"]
    target_cols = ["margin", "total"]
    feature_cols = [c for c in feats.columns if c != "game_id"]

    # finalize X
    X = df[feature_cols].to_numpy(dtype=float)
    y_margin = df["margin"].to_numpy(dtype=float)
    y_total = df["total"].to_numpy(dtype=float)

    dev_idx = np.asarray(splits.dev_indices, dtype=int)
    hold_idx = np.asarray(splits.holdout_indices, dtype=int)
    fut_idx = np.asarray(splits.future_indices, dtype=int)

    X_dev, X_hold = X[dev_idx], X[hold_idx]
    y_margin_dev, y_margin_hold = y_margin[dev_idx], y_margin[hold_idx]
    y_total_dev, y_total_hold = y_total[dev_idx], y_total[hold_idx]

    if len(fut_idx) == 0:
        raise RuntimeError("SPLITS.json has no future_indices. Recreate splits with scripts/04_make_splits.py")

    X_fut, y_margin_fut, y_total_fut = X[fut_idx], y_margin[fut_idx], y_total[fut_idx]

    # Baselines estimated from DEV only
    hca = estimate_hca_from_dev(y_margin_dev)
    total_mean = estimate_total_mean_from_dev(y_total_dev)

    baseline_margin_hold = predict_margin_constant(len(hold_idx), hca)
    baseline_total_hold = predict_total_constant(len(hold_idx), total_mean)
    baseline_margin_fut = predict_margin_constant(len(fut_idx), hca)
    baseline_total_fut = predict_total_constant(len(fut_idx), total_mean)

    baseline_win_hold = winner_metrics_from_margin(y_margin_hold, baseline_margin_hold).win_acc
    baseline_win_fut = winner_metrics_from_margin(y_margin_fut, baseline_margin_fut).win_acc

    cv_folds = splits.cv_folds

    # Hyperparameter tuning (Optuna) — DEV ONLY
    # Pre-registered methodology: tune each (model_type, target) with walk-forward CV objective.
    # IMPORTANT: results are cached; re-running should NOT retune unless you delete the artifacts.
    tuning_trials = 200
    tuned: dict[tuple[str, str], dict] = {}

    for model_type in ["catboost", "xgboost"]:
        for target in ["margin", "total"]:
            out_path = artifacts_dir() / f"OPTUNA_{model_type}_{target}.json"
            if out_path.exists():
                payload = json.loads(out_path.read_text(encoding="utf-8"))
                tuned[(model_type, target)] = payload["best"]["params"]
                continue

            params = tune_model_params(
                X_dev=X_dev,
                y_margin_dev=y_margin_dev,
                y_total_dev=y_total_dev,
                cv_folds=cv_folds,
                spec=TuningSpec(model_type=model_type, target=target, n_trials=tuning_trials, seed=2025),
                out_path=out_path,
            )
            tuned[(model_type, target)] = params

    # Seed sweep (repeatability) on dev CV (USING tuned hyperparams)
    seeds = list(range(42, 72))  # 30 seeds

    sweep_cb = _seed_sweep(
        X_dev,
        y_margin_dev,
        y_total_dev,
        cv_folds,
        model_type="catboost",
        seeds=seeds,
        params_margin=tuned[("catboost", "margin")],
        params_total=tuned[("catboost", "total")],
    )
    sweep_xgb = _seed_sweep(
        X_dev,
        y_margin_dev,
        y_total_dev,
        cv_folds,
        model_type="xgboost",
        seeds=seeds,
        params_margin=tuned[("xgboost", "margin")],
        params_total=tuned[("xgboost", "total")],
    )
    sweep = pd.concat([sweep_cb, sweep_xgb], ignore_index=True)

    seed_sweep_path = artifacts_dir() / "SEED_SWEEP_SUMMARY.csv"
    sweep.to_csv(seed_sweep_path, index=False)

    # Repeatability gates (use margin metrics)
    rep = (
        sweep.groupby("model")
        .agg({"margin_mae": ["mean", "std"], "margin_win_acc": ["mean", "std"]})
        .reset_index()
    )

    # Train final models on full dev and evaluate holdout + future (one time)
    results_holdout = []
    results_future = []
    holdout_pred_rows = []
    future_pred_rows = []

    for model_type in ["catboost", "xgboost"]:
        for target, y_dev, y_h, baseline_h in [
            ("margin", y_margin_dev, y_margin_hold, baseline_margin_hold),
            ("total", y_total_dev, y_total_hold, baseline_total_hold),
        ]:
            cfg = ModelConfig(model_type=model_type, target=target, seed=42, params=tuned[(model_type, target)])
            model = train_model(X_dev, y_dev, cfg)

            # holdout eval
            pred = model.predict(X_hold)
            met = regression_metrics(y_h, pred)
            if target == "margin":
                win = winner_metrics_from_margin(y_h, pred)
                base_win = baseline_win_hold
                win_lift_pp = (win.win_acc - base_win) * 100.0
            else:
                win = None
                win_lift_pp = None

            base_met = regression_metrics(y_h, baseline_h)

            results_holdout.append(
                {
                    "model": model_type,
                    "target": target,
                    "mae": met.mae,
                    "rmse": met.rmse,
                    "baseline_mae": base_met.mae,
                    "mae_improvement": base_met.mae - met.mae,
                    "win_acc": (win.win_acc if win else np.nan),
                    "baseline_win_acc": (base_win if target == "margin" else np.nan),
                    "win_acc_improvement_pp": (win_lift_pp if target == "margin" else np.nan),
                }
            )

            # store per-game predictions for holdout
            for j, idx in enumerate(hold_idx):
                base = df.iloc[idx][id_cols].to_dict()
                base.update(
                    {"split": "holdout", "target": target, "model": model_type, "y_true": float(y_h[j]), "y_pred": float(pred[j])}
                )
                holdout_pred_rows.append(base)

            # future eval
            if target == "margin":
                y_f = y_margin_fut
                baseline_f = baseline_margin_fut
            else:
                y_f = y_total_fut
                baseline_f = baseline_total_fut

            pred_f = model.predict(X_fut)
            met_f = regression_metrics(y_f, pred_f)
            if target == "margin":
                win_f = winner_metrics_from_margin(y_f, pred_f)
                base_win_f = baseline_win_fut
                win_lift_f_pp = (win_f.win_acc - base_win_f) * 100.0
            else:
                win_f = None
                base_win_f = np.nan
                win_lift_f_pp = np.nan

            base_met_f = regression_metrics(y_f, baseline_f)

            results_future.append(
                {
                    "model": model_type,
                    "target": target,
                    "mae": met_f.mae,
                    "rmse": met_f.rmse,
                    "baseline_mae": base_met_f.mae,
                    "mae_improvement": base_met_f.mae - met_f.mae,
                    "win_acc": (win_f.win_acc if win_f else np.nan),
                    "baseline_win_acc": (base_win_f if target == "margin" else np.nan),
                    "win_acc_improvement_pp": (win_lift_f_pp if target == "margin" else np.nan),
                }
            )

            for j, idx in enumerate(fut_idx):
                base = df.iloc[idx][id_cols].to_dict()
                base.update(
                    {
                        "split": "future",
                        "target": target,
                        "model": model_type,
                        "y_true": float(y_f[j]),
                        "y_pred": float(pred_f[j]),
                    }
                )
                future_pred_rows.append(base)

            # Bootstrap for margin only vs baseline (HOLDOUT ONLY, per protocol)
            if target == "margin":
                boot = paired_bootstrap_ci(y_h, pred, baseline_h, n_boot=10_000, seed=123)
                (artifacts_dir() / f"BOOTSTRAP_{model_type}_margin.json").write_text(
                    json.dumps(boot, indent=2), encoding="utf-8"
                )

    holdout_pred_path = artifacts_dir() / "HOLDOUT_PREDICTIONS.csv"
    pd.DataFrame(holdout_pred_rows).to_csv(holdout_pred_path, index=False)

    future_pred_path = artifacts_dir() / "FUTURE_PREDICTIONS.csv"
    pd.DataFrame(future_pred_rows).to_csv(future_pred_path, index=False)

    holdout_summary = pd.DataFrame(results_holdout)
    future_summary = pd.DataFrame(results_future)

    # Red team tests (DEV only) using CatBoost for margin
    # core features = only elo + rest + sos (minimal)
    core_cols = [c for c in feature_cols if c.startswith("home_elo") or c.startswith("away_elo") or c.startswith("elo_")]
    core_cols += [c for c in feature_cols if c.startswith("rest_") or c.startswith("b2b_") or c.startswith("games_last")]
    core_cols += [c for c in feature_cols if "sos" in c]
    core_cols = sorted(set(core_cols))

    X_dev_core = df.iloc[dev_idx][core_cols].to_numpy(dtype=float)

    rt_perm = permutation_test(X_dev, y_margin_dev, cv_folds=cv_folds, model_type="catboost", seed=999, n_reps=10)
    rt_rev = time_reversal_test(X_dev, y_margin_dev, model_type="catboost", seed=999)
    rt_abl = ablation_test(X_full=X_dev, X_core=X_dev_core, y=y_margin_dev, cv_folds=cv_folds, model_type="catboost", seed=999)

    red_team_path = reports_dir() / "RED_TEAM_REPORT.md"
    red_lines = [
        "# Red Team Report (Maximus)",
        "",
        f"Generated at: {datetime.now(timezone.utc).isoformat()}",
        "",
        f"## Permutation Test\n- passed: {rt_perm.passed}\n- details: {rt_perm.details}",
        "",
        f"## Time Reversal Test\n- passed: {rt_rev.passed}\n- details: {rt_rev.details}",
        "",
        f"## Ablation Test\n- passed: {rt_abl.passed}\n- details: {rt_abl.details}\n- core_features_count: {len(core_cols)}",
    ]
    red_team_path.write_text("\n".join(red_lines), encoding="utf-8")

    # Drift report
    # Use fold-level MAE trend from seed=42 CV
    cv_42 = walkforward_oof_predictions(X_dev, y_margin_dev, y_total_dev, cv_folds=cv_folds, model_type="catboost", seed=42)
    fold_mae = [f.mae for f in cv_42["margin"]["folds"]]
    trend = fold_trend_test(fold_mae)

    drift_feat_hold = feature_drift_summary(
        pd.DataFrame(X_dev, columns=feature_cols), pd.DataFrame(X_hold, columns=feature_cols)
    )
    drift_feat_future = feature_drift_summary(
        pd.DataFrame(X_dev, columns=feature_cols), pd.DataFrame(X_fut, columns=feature_cols)
    )

    drift_path = reports_dir() / "DRIFT_REPORT.md"
    drift_lines = [
        "# Drift Report (Maximus)",
        "",
        f"Generated at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Performance Trend (walk-forward CV, CatBoost margin, seed=42)",
        f"- fold_mae: {fold_mae}",
        f"- trend: {trend}",
        "",
        "## Feature Drift Summary (dev vs holdout)",
        f"- summary: {drift_feat_hold}",
        "",
        "## Feature Drift Summary (dev vs future block)",
        f"- summary: {drift_feat_future}",
        "",
        "## Monitoring Thresholds (initial)",
        "- alert if pct_features_shift_gt_1_0z > 0.25",
        "- alert if margin MAE rolling 7d worsens by >10% vs holdout",
        "- retrain if triggered for 3 consecutive days",
    ]
    drift_path.write_text("\n".join(drift_lines), encoding="utf-8")

    # Gate evaluation
    # We pick best baseline for margin as constant HCA (estimated from dev)
    # Evaluate gates on CatBoost margin (primary)
    primary = holdout_summary[(holdout_summary["model"] == "catboost") & (holdout_summary["target"] == "margin")].iloc[0]
    primary_future = future_summary[(future_summary["model"] == "catboost") & (future_summary["target"] == "margin")].iloc[0]

    # load bootstrap
    boot = json.loads((artifacts_dir() / "BOOTSTRAP_catboost_margin.json").read_text(encoding="utf-8"))

    # repeatability stats for catboost
    cb_sweep = sweep[sweep["model"] == "catboost"]
    std_mae = float(cb_sweep["margin_mae"].std(ddof=0))
    std_win_pp = float(cb_sweep["margin_win_acc"].std(ddof=0) * 100.0)

    # Future stress gates compare CatBoost margin holdout vs future
    holdout_mae = float(primary["mae"])
    holdout_win = float(primary["win_acc"])
    future_mae = float(primary_future["mae"])
    future_win = float(primary_future["win_acc"])

    gates = {
        "holdout_mae_improvement": {
            "value": float(primary["mae_improvement"]),
            "required": SUCCESS_CRITERIA["holdout_mae_improvement_min"],
            "pass": bool(primary["mae_improvement"] >= SUCCESS_CRITERIA["holdout_mae_improvement_min"]),
        },
        "holdout_win_acc_improvement_pp": {
            "value": float(primary["win_acc_improvement_pp"]),
            "required": SUCCESS_CRITERIA["holdout_win_acc_improvement_min_pp"],
            "pass": bool(primary["win_acc_improvement_pp"] >= SUCCESS_CRITERIA["holdout_win_acc_improvement_min_pp"]),
        },
        "bootstrap_mae_ci": {
            "ci95": boot["mae_delta"]["ci95"],
            "pass": bool(boot["mae_delta"]["pass"]),
        },
        "bootstrap_win_ci": {
            "ci95": boot["win_acc_delta"]["ci95"],
            "pass": bool(boot["win_acc_delta"]["pass"]),
        },
        "repeatability": {
            "std_mae": std_mae,
            "std_win_acc_pp": std_win_pp,
            "required": {
                "std_mae_max": SUCCESS_CRITERIA["repeatability_std_mae_max"],
                "std_win_acc_pp_max": SUCCESS_CRITERIA["repeatability_std_win_acc_pp_max"],
            },
            "pass": bool(
                std_mae <= SUCCESS_CRITERIA["repeatability_std_mae_max"]
                and std_win_pp <= SUCCESS_CRITERIA["repeatability_std_win_acc_pp_max"]
            ),
        },
        "red_team": {
            "permutation": {"pass": rt_perm.passed, "details": rt_perm.details},
            "time_reversal": {"pass": rt_rev.passed, "details": rt_rev.details},
            "ablation": {"pass": rt_abl.passed, "details": rt_abl.details},
            "pass": bool(rt_perm.passed and rt_rev.passed and rt_abl.passed),
        },
        "future_mae_stress": {
            "holdout_mae": holdout_mae,
            "future_mae": future_mae,
            "max_multiplier": SUCCESS_CRITERIA["future_mae_max_multiplier"],
            "pass": bool(future_mae <= holdout_mae * SUCCESS_CRITERIA["future_mae_max_multiplier"]),
        },
        "future_win_acc_stress": {
            "holdout_win_acc": holdout_win,
            "future_win_acc": future_win,
            "max_drop_pp": SUCCESS_CRITERIA["future_win_acc_drop_max_pp"],
            "pass": bool((holdout_win - future_win) * 100.0 <= SUCCESS_CRITERIA["future_win_acc_drop_max_pp"]),
        },
    }

    all_pass = all(v["pass"] for v in gates.values())
    decision = "GO" if all_pass else "NO-GO"

    go_no_go = {
        "project": "Maximus",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "gates": gates,
        "primary_model": {"model": "catboost", "target": "margin", "seed": 42},
    }
    (artifacts_dir() / "GO_NO_GO.json").write_text(json.dumps(go_no_go, indent=2), encoding="utf-8")

    # training report + evaluation report
    (reports_dir() / "MODEL_TRAINING_REPORT.md").write_text(
        "\n".join(
            [
                "# Model Training Report (Maximus)",
                "",
                f"Generated at: {datetime.now(timezone.utc).isoformat()}",
                "",
                "## Hyperparameters",
                "- Tuned via Optuna on DEV walk-forward CV (see artifacts/OPTUNA_*.json)",
                "- Final training uses best params per (model, target)",
                "",
                "## Seeds",
                "- Primary seed: 42",
                "- Seed sweep: 42..61",
            ]
        ),
        encoding="utf-8",
    )

    eval_lines = [
        "# Evaluation Report (Maximus)",
        "",
        f"Generated at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Baselines (DEV-estimated)",
        f"- margin HCA estimate (from dev): {hca:.4f}",
        f"- total mean estimate (from dev): {total_mean:.4f}",
        f"- holdout baseline margin win_acc: {baseline_win_hold*100:.2f}%",
        f"- future baseline margin win_acc: {baseline_win_fut*100:.2f}%",
        "",
        "## Hyperparameter Tuning (Optuna; dev-only)",
        "Artifacts:",
        "- artifacts/OPTUNA_catboost_margin.json",
        "- artifacts/OPTUNA_catboost_total.json",
        "- artifacts/OPTUNA_xgboost_margin.json",
        "- artifacts/OPTUNA_xgboost_total.json",
        "",
        "## Holdout Results (one-time)",
        holdout_summary.to_string(index=False),
        "",
        "## Future Block Results (deployment simulation; not used for tuning)",
        future_summary.to_string(index=False),
        "",
        "## Bootstrap (CatBoost margin vs baseline HCA) (B=10,000)",
        json.dumps(boot, indent=2),
        "",
        "## Repeatability (seed sweep summary written to artifacts)",
        rep.to_string(index=False),
        "",
        f"## Red Team\nSee: {red_team_path}",
        "",
        f"## Drift\nSee: {drift_path}",
        "",
        "## Final Decision",
        json.dumps(go_no_go, indent=2),
    ]
    (reports_dir() / "EVALUATION_REPORT.md").write_text("\n".join(eval_lines), encoding="utf-8")

    # RUN_MANIFEST.json
    # include processed dataset hashes if available
    proc_matrix = Path(__file__).resolve().parents[1] / "data" / "processed" / "model_matrix.parquet"
    feature_build_manifest = artifacts_dir() / "FEATURE_BUILD_MANIFEST.json"

    run_manifest = {
        "project": "Maximus",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "code_version": {"git_sha": git_sha},
        "inputs": {
            "raw_snapshot_manifest": str((artifacts_dir() / "RAW_SNAPSHOT_MANIFEST.json").resolve()),
            "splits": str(split_path.resolve()),
            "feature_build_manifest": str(feature_build_manifest.resolve()) if feature_build_manifest.exists() else None,
        },
        "data_hashes": {
            "splits_sha256": sha256_file(split_path),
            "model_matrix_sha256": sha256_file(proc_matrix) if proc_matrix.exists() else None,
        },
        "success_criteria": SUCCESS_CRITERIA,
        "notes": "Holdout evaluated once; no post-hoc threshold changes allowed.",
    }
    (artifacts_dir() / "RUN_MANIFEST.json").write_text(json.dumps(run_manifest, indent=2), encoding="utf-8")

    print(f"Wrote GO/NO-GO: {artifacts_dir() / 'GO_NO_GO.json'}")
    print(f"Wrote holdout preds: {holdout_pred_path}")
    print(f"Wrote future preds: {future_pred_path}")
    print(f"Decision: {decision}")

    # Fail fast: if any gate fails, stop and instruct.
    if decision == "NO-GO":
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

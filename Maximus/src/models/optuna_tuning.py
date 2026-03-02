from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from Maximus.src.eval.walkforward import walkforward_oof_single_target


@dataclass(frozen=True)
class TuningSpec:
    model_type: str  # "xgboost" | "catboost"
    target: str  # "margin" | "total"
    n_trials: int
    seed: int


def _xgb_search_space(trial) -> dict:
    return {
        # keep it sane; no 300-dim search space clownery
        "n_estimators": trial.suggest_int("n_estimators", 300, 2000),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
        "max_depth": trial.suggest_int("max_depth", 3, 8),
        "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
        "min_child_weight": trial.suggest_float("min_child_weight", 0.5, 10.0, log=True),
        "gamma": trial.suggest_float("gamma", 0.0, 5.0),
        "reg_lambda": trial.suggest_float("reg_lambda", 1e-3, 50.0, log=True),
    }


def _cb_search_space(trial) -> dict:
    return {
        "iterations": trial.suggest_int("iterations", 400, 3000),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
        "depth": trial.suggest_int("depth", 4, 10),
        "l2_leaf_reg": trial.suggest_float("l2_leaf_reg", 1e-2, 50.0, log=True),
        "bagging_temperature": trial.suggest_float("bagging_temperature", 0.0, 2.0),
        "random_strength": trial.suggest_float("random_strength", 0.0, 2.0),
    }


def tune_model_params(
    *,
    X_dev: np.ndarray,
    y_margin_dev: np.ndarray,
    y_total_dev: np.ndarray,
    cv_folds: list[dict],
    spec: TuningSpec,
    out_path: Path,
) -> dict:
    """Tune hyperparameters with Optuna on DEV only.

    Objective: minimize global OOF MAE for the requested target.

    Writes:
      - out_path JSON with study config, best params, and trial history.
    """

    import optuna

    out_path.parent.mkdir(parents=True, exist_ok=True)

    def objective(trial: optuna.Trial) -> float:
        if spec.model_type == "xgboost":
            params = _xgb_search_space(trial)
        elif spec.model_type == "catboost":
            params = _cb_search_space(trial)
        else:
            raise ValueError(f"Unknown model_type: {spec.model_type}")

        if spec.target == "margin":
            res = walkforward_oof_single_target(
                X=X_dev,
                y=y_margin_dev,
                cv_folds=cv_folds,
                model_type=spec.model_type,
                target="margin",
                seed=spec.seed,
                params=params,
            )
            return float(res["global"]["mae"])

        if spec.target == "total":
            res = walkforward_oof_single_target(
                X=X_dev,
                y=y_total_dev,
                cv_folds=cv_folds,
                model_type=spec.model_type,
                target="total",
                seed=spec.seed,
                params=params,
            )
            return float(res["global"]["mae"])

        raise ValueError(f"Unknown target: {spec.target}")

    sampler = optuna.samplers.TPESampler(seed=spec.seed)
    study = optuna.create_study(direction="minimize", sampler=sampler)
    def heartbeat(study, trial):
        # Minimal progress without log spam
        if trial.number == 0 or (trial.number + 1) % 10 == 0:
            best = study.best_value if study.best_trial is not None else None
            print(
                f"[optuna] {spec.model_type}/{spec.target} trial {trial.number + 1}/{spec.n_trials} done; "
                f"value={trial.value} best={best}",
                flush=True,
            )

    # Never let a single bad trial crash the whole run.
    study.optimize(
        objective,
        n_trials=spec.n_trials,
        show_progress_bar=False,
        callbacks=[heartbeat],
        catch=(Exception,),
    )

    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "spec": {
            "model_type": spec.model_type,
            "target": spec.target,
            "n_trials": spec.n_trials,
            "seed": spec.seed,
        },
        "best": {
            "value": float(study.best_value),
            "params": dict(study.best_params),
        },
        "trials": [
            {
                "number": t.number,
                "value": float(t.value) if t.value is not None else None,
                "params": dict(t.params),
                "state": str(t.state),
            }
            for t in study.trials
        ],
    }

    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload["best"]["params"]

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ModelConfig:
    model_type: str  # "xgboost" or "catboost"
    target: str  # "margin" or "total"
    seed: int
    params: dict


def train_xgboost_regressor(X: np.ndarray, y: np.ndarray, seed: int, params: dict):
    import xgboost as xgb

    base = {
        "objective": "reg:squarederror",
        "n_estimators": 800,
        "learning_rate": 0.03,
        "max_depth": 5,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
        "reg_lambda": 1.0,
        "min_child_weight": 1.0,
        "gamma": 0.0,
        "random_state": seed,
        "n_jobs": -1,
    }
    base.update(params or {})

    return xgb.XGBRegressor(**base).fit(X, y)


def train_catboost_regressor(X: np.ndarray, y: np.ndarray, seed: int, params: dict):
    import catboost as cb

    base = {
        "iterations": 1200,
        "learning_rate": 0.03,
        "depth": 6,
        "loss_function": "MAE",
        "random_seed": seed,
        "verbose": False,
        "allow_writing_files": False,
    }
    base.update(params or {})

    return cb.CatBoostRegressor(**base).fit(X, y)


def train_model(X: np.ndarray, y: np.ndarray, cfg: ModelConfig):
    if cfg.model_type == "xgboost":
        return train_xgboost_regressor(X, y, cfg.seed, cfg.params)
    if cfg.model_type == "catboost":
        return train_catboost_regressor(X, y, cfg.seed, cfg.params)
    raise ValueError(f"Unknown model_type: {cfg.model_type}")

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from Maximus.src.eval.metrics import regression_metrics, winner_metrics_from_margin
from Maximus.src.models.trainers import ModelConfig, train_model


@dataclass(frozen=True)
class FoldResult:
    fold_index: int
    n_train: int
    n_test: int
    mae: float
    rmse: float
    win_acc: float


def walkforward_oof_single_target(
    *,
    X: np.ndarray,
    y: np.ndarray,
    cv_folds: list[dict],
    model_type: str,
    target: str,
    seed: int,
    params: dict | None = None,
) -> dict:
    """Walk-forward CV for a single target.

    Returns:
      {"oof_pred": array, "folds": [...], "global": {"mae": ..., "rmse": ..., "win_acc": ...?}}

    NOTE:
    - Metrics are computed on concatenated OOF predictions (global), not mean of fold means.
    """

    n = len(y)
    oof = np.full(n, np.nan, dtype=float)
    fold_rows: list[FoldResult] = []

    for i, fold in enumerate(cv_folds, start=1):
        tr_idx = np.asarray(fold["train_indices"], dtype=int)
        te_idx = np.asarray(fold["test_indices"], dtype=int)

        X_tr, X_te = X[tr_idx], X[te_idx]

        cfg = ModelConfig(model_type=model_type, target=target, seed=seed, params=(params or {}))
        m = train_model(X_tr, y[tr_idx], cfg)
        pred = m.predict(X_te)
        oof[te_idx] = pred

        met = regression_metrics(y[te_idx], pred)
        win_acc = winner_metrics_from_margin(y[te_idx], pred).win_acc if target == "margin" else float("nan")
        fold_rows.append(
            FoldResult(
                fold_index=i,
                n_train=len(tr_idx),
                n_test=len(te_idx),
                mae=met.mae,
                rmse=met.rmse,
                win_acc=win_acc,
            )
        )

    # Walk-forward does not predict the initial training prefix by design.
    # We compute metrics only on the union of test indices (i.e., where OOF is present).
    mask = ~np.isnan(oof)
    if not mask.any():
        raise RuntimeError(f"No OOF predictions produced for target={target}")

    global_met = regression_metrics(y[mask], oof[mask])
    global_win = winner_metrics_from_margin(y[mask], oof[mask]).win_acc if target == "margin" else float("nan")

    return {
        "oof_pred": oof,
        "folds": fold_rows,
        "global": {"mae": global_met.mae, "rmse": global_met.rmse, "win_acc": global_win, "n_oof": int(mask.sum())},
    }


def walkforward_oof_predictions(
    X: np.ndarray,
    y_margin: np.ndarray,
    y_total: np.ndarray,
    cv_folds: list[dict],
    model_type: str,
    seed: int,
    params_margin: dict | None = None,
    params_total: dict | None = None,
) -> dict:
    """Train and predict OOF on dev folds for both targets using identical folds.

    Returns:
      {
        "margin": {"oof_pred": array, "folds": [...]},
        "total": {"oof_pred": array, "folds": [...]},
      }

    IMPORTANT:
    - Metrics are computed on concatenated OOF predictions (global), not mean of fold means.
    """

    n = len(y_margin)
    oof_margin = np.full(n, np.nan, dtype=float)
    oof_total = np.full(n, np.nan, dtype=float)

    fold_rows_margin: list[FoldResult] = []
    fold_rows_total: list[FoldResult] = []

    for i, fold in enumerate(cv_folds, start=1):
        tr_idx = np.asarray(fold["train_indices"], dtype=int)
        te_idx = np.asarray(fold["test_indices"], dtype=int)

        X_tr, X_te = X[tr_idx], X[te_idx]

        # margin model
        m_cfg = ModelConfig(model_type=model_type, target="margin", seed=seed, params=(params_margin or {}))
        m = train_model(X_tr, y_margin[tr_idx], m_cfg)
        pred_m = m.predict(X_te)
        oof_margin[te_idx] = pred_m

        met_m = regression_metrics(y_margin[te_idx], pred_m)
        win_m = winner_metrics_from_margin(y_margin[te_idx], pred_m)
        fold_rows_margin.append(
            FoldResult(
                fold_index=i,
                n_train=len(tr_idx),
                n_test=len(te_idx),
                mae=met_m.mae,
                rmse=met_m.rmse,
                win_acc=win_m.win_acc,
            )
        )

        # total model
        t_cfg = ModelConfig(model_type=model_type, target="total", seed=seed, params=(params_total or {}))
        t = train_model(X_tr, y_total[tr_idx], t_cfg)
        pred_t = t.predict(X_te)
        oof_total[te_idx] = pred_t

        met_t = regression_metrics(y_total[te_idx], pred_t)
        # total doesn't have win acc; store as NaN
        fold_rows_total.append(
            FoldResult(
                fold_index=i,
                n_train=len(tr_idx),
                n_test=len(te_idx),
                mae=met_t.mae,
                rmse=met_t.rmse,
                win_acc=float("nan"),
            )
        )

    # Walk-forward does not predict the initial training prefix by design.
    m_mask = ~np.isnan(oof_margin)
    t_mask = ~np.isnan(oof_total)
    if not m_mask.any() or not t_mask.any():
        raise RuntimeError(
            f"No OOF predictions produced: margin_n={int(m_mask.sum())}, total_n={int(t_mask.sum())}"
        )

    # Global (concatenated) metrics on predicted region only
    global_m = regression_metrics(y_margin[m_mask], oof_margin[m_mask])
    global_w = winner_metrics_from_margin(y_margin[m_mask], oof_margin[m_mask])
    global_t = regression_metrics(y_total[t_mask], oof_total[t_mask])

    return {
        "margin": {
            "oof_pred": oof_margin,
            "folds": fold_rows_margin,
            "global": {"mae": global_m.mae, "rmse": global_m.rmse, "win_acc": global_w.win_acc, "n_oof": int(m_mask.sum())},
        },
        "total": {
            "oof_pred": oof_total,
            "folds": fold_rows_total,
            "global": {"mae": global_t.mae, "rmse": global_t.rmse, "n_oof": int(t_mask.sum())},
        },
    }

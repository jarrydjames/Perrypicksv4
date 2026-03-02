from __future__ import annotations

import numpy as np


def paired_bootstrap_ci(
    y_true: np.ndarray,
    pred_model: np.ndarray,
    pred_baseline: np.ndarray,
    n_boot: int = 10_000,
    seed: int = 123,
) -> dict:
    """Paired bootstrap CI for deltas (model - baseline).

    Returns 95% CI for:
    - MAE delta (lower is better; want CI entirely < 0)
    - Win acc delta (higher is better; want CI entirely > 0)

    Win accuracy is derived from sign(pred_margin) vs sign(y_true_margin),
    so use only for margin target.
    """

    rng = np.random.default_rng(seed)
    y_true = np.asarray(y_true, dtype=float)
    pred_model = np.asarray(pred_model, dtype=float)
    pred_baseline = np.asarray(pred_baseline, dtype=float)

    n = len(y_true)
    idx = rng.integers(0, n, size=(n_boot, n))

    # MAE deltas
    mae_model = np.abs(y_true[idx] - pred_model[idx]).mean(axis=1)
    mae_base = np.abs(y_true[idx] - pred_baseline[idx]).mean(axis=1)
    mae_delta = mae_model - mae_base

    # Win accuracy deltas
    yt = np.sign(y_true[idx])
    wm = (np.sign(pred_model[idx]) == yt).mean(axis=1)
    wb = (np.sign(pred_baseline[idx]) == yt).mean(axis=1)
    win_delta = wm - wb

    def ci(a: np.ndarray) -> tuple[float, float]:
        return float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5))

    mae_ci = ci(mae_delta)
    win_ci = ci(win_delta)

    return {
        "n_boot": int(n_boot),
        "seed": int(seed),
        "mae_delta": {
            "mean": float(mae_delta.mean()),
            "ci95": [mae_ci[0], mae_ci[1]],
            "pass": bool(mae_ci[1] < 0.0),
        },
        "win_acc_delta": {
            "mean": float(win_delta.mean()),
            "ci95": [win_ci[0], win_ci[1]],
            "pass": bool(win_ci[0] > 0.0),
        },
    }

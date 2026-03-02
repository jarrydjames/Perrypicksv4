from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class RegressionMetrics:
    mae: float
    rmse: float


@dataclass(frozen=True)
class WinnerMetrics:
    win_acc: float
    tp: int
    tn: int
    fp: int
    fn: int


def regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> RegressionMetrics:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    err = y_true - y_pred
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err**2)))
    return RegressionMetrics(mae=mae, rmse=rmse)


def winner_metrics_from_margin(y_true_margin: np.ndarray, y_pred_margin: np.ndarray) -> WinnerMetrics:
    yt = np.sign(np.asarray(y_true_margin, dtype=float))
    yp = np.sign(np.asarray(y_pred_margin, dtype=float))

    # no pushes expected; if there are, treat sign=0 as incorrect
    correct = yt == yp
    win_acc = float(np.mean(correct))

    # confusion matrix based on positive (home win) as class 1
    yt_pos = yt > 0
    yp_pos = yp > 0

    tp = int(np.sum(yt_pos & yp_pos))
    tn = int(np.sum((~yt_pos) & (~yp_pos)))
    fp = int(np.sum((~yt_pos) & yp_pos))
    fn = int(np.sum(yt_pos & (~yp_pos)))

    return WinnerMetrics(win_acc=win_acc, tp=tp, tn=tn, fp=fp, fn=fn)

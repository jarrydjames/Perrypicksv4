from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from Maximus.src.eval.decision import DecisionPolicy, win_acc_with_abstain


@dataclass(frozen=True)
class ThresholdCalibrationResult:
    threshold: float
    win_acc: float
    coverage: float


def calibrate_margin_threshold(
    y_true_margin: np.ndarray,
    pred_margin: np.ndarray,
    *,
    candidate_thresholds: list[float],
    min_coverage: float = 0.70,
) -> ThresholdCalibrationResult:
    """Choose a threshold on |pred_margin| using only provided data.

    This is meant to run on DEV OOF predictions.

    Selection rule:
    - maximize win_acc subject to coverage >= min_coverage
    - tie-breaker: highest coverage

    Raises:
      ValueError if no candidate meets min_coverage.
    """

    best: ThresholdCalibrationResult | None = None

    for t in candidate_thresholds:
        met = win_acc_with_abstain(y_true_margin, pred_margin, DecisionPolicy(threshold=float(t)))
        win_acc = met["win_acc"]
        coverage = met["coverage"]

        if coverage < min_coverage or np.isnan(win_acc):
            continue

        cand = ThresholdCalibrationResult(threshold=float(t), win_acc=float(win_acc), coverage=float(coverage))

        if best is None:
            best = cand
            continue

        if cand.win_acc > best.win_acc + 1e-12:
            best = cand
        elif abs(cand.win_acc - best.win_acc) <= 1e-12 and cand.coverage > best.coverage:
            best = cand

    if best is None:
        raise ValueError("No threshold met min_coverage")

    return best


def calibrate_margin_threshold_by_folds(
    *,
    y_true_margin: np.ndarray,
    pred_margin: np.ndarray,
    cv_folds: list[dict],
    candidate_thresholds: list[float],
    min_coverage: float = 0.70,
    use_last_k_folds: int = 10,
) -> ThresholdCalibrationResult:
    """Calibrate threshold using fold-wise robustness.

    Uses only samples that have OOF predictions.

    Selection rule:
    - for each candidate threshold, compute per-fold win_acc and coverage on test indices
    - restrict to last K folds (most recent) to better match deployment regime
    - require mean coverage >= min_coverage
    - maximize worst_fold_win_acc (min over folds)
    - tie-breaker: higher mean win_acc, then higher mean coverage
    """

    y_true_margin = np.asarray(y_true_margin, dtype=float)
    pred_margin = np.asarray(pred_margin, dtype=float)

    # determine which folds to use
    folds = cv_folds[-use_last_k_folds:] if use_last_k_folds and len(cv_folds) > use_last_k_folds else cv_folds

    best: ThresholdCalibrationResult | None = None

    from Maximus.src.eval.decision import DecisionPolicy, win_acc_with_abstain

    for t in candidate_thresholds:
        policy = DecisionPolicy(threshold=float(t))
        fold_win = []
        fold_cov = []

        for f in folds:
            te = np.asarray(f["test_indices"], dtype=int)
            # only evaluate where we have predictions
            m = ~np.isnan(pred_margin[te])
            if m.sum() == 0:
                continue
            met = win_acc_with_abstain(y_true_margin[te][m], pred_margin[te][m], policy)
            fold_win.append(met["win_acc"])
            fold_cov.append(met["coverage"])

        if not fold_win:
            continue

        mean_cov = float(np.mean(fold_cov))
        if mean_cov < min_coverage:
            continue

        worst_win = float(np.min(fold_win))
        mean_win = float(np.mean(fold_win))

        cand = ThresholdCalibrationResult(threshold=float(t), win_acc=mean_win, coverage=mean_cov)

        if best is None:
            best = cand
            best_key = (worst_win, mean_win, mean_cov)
            continue

        cand_key = (worst_win, mean_win, mean_cov)
        if cand_key > best_key:
            best = cand
            best_key = cand_key

    if best is None:
        raise ValueError("No threshold met min_coverage under fold-wise calibration")

    return best

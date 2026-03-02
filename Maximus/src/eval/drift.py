from __future__ import annotations

import numpy as np
import pandas as pd
from pandas import DataFrame
from scipy import stats


def fold_trend_test(fold_mae: list[float]) -> dict:
    x = np.arange(1, len(fold_mae) + 1, dtype=float)
    y = np.asarray(fold_mae, dtype=float)
    slope, intercept, r, p, stderr = stats.linregress(x, y)
    return {
        "slope": float(slope),
        "p_value": float(p),
        "r": float(r),
        "stderr": float(stderr),
        "n_folds": int(len(fold_mae)),
    }


def feature_drift_summary(X_dev: DataFrame, X_holdout: DataFrame) -> dict:
    """Simple drift stats: mean/std shift per feature.

    For audit-defensible monitoring, we’ll also add PSI later.
    """

    means_dev = X_dev.mean()
    means_hold = X_holdout.mean()
    std_dev = X_dev.std(ddof=0).replace(0.0, 1e-9)

    mean_shift_z = ((means_hold - means_dev) / std_dev).abs()

    return {
        "mean_abs_shift_z": float(mean_shift_z.mean()),
        "pct_features_shift_gt_0_5z": float((mean_shift_z > 0.5).mean()),
        "pct_features_shift_gt_1_0z": float((mean_shift_z > 1.0).mean()),
        "top10_mean_shift_z": mean_shift_z.sort_values(ascending=False).head(10).to_dict(),
    }

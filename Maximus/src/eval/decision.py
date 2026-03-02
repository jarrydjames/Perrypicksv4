from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class DecisionPolicy:
    """Policy for converting margin predictions into winner picks.

    - threshold: require predicted margin magnitude >= threshold to make a pick
    - abstain_value: label used for abstentions in outputs

    Notes:
    - This does NOT change the regression prediction; it only changes the
      discrete decision rule.
    - If threshold == 0.0, this is the standard sign(pred) rule.
    """

    threshold: float = 0.0


def picks_from_margin(pred_margin: np.ndarray, policy: DecisionPolicy) -> np.ndarray:
    pred_margin = np.asarray(pred_margin, dtype=float)
    out = np.full(pred_margin.shape, fill_value=np.nan, dtype=float)

    # pick home=1, away=0
    out[pred_margin > policy.threshold] = 1.0
    out[pred_margin < -policy.threshold] = 0.0
    # abstain remains NaN
    return out


def win_acc_with_abstain(y_true_margin: np.ndarray, pred_margin: np.ndarray, policy: DecisionPolicy) -> dict:
    """Compute win accuracy with optional abstention.

    Returns:
      {"win_acc": float, "coverage": float}

    coverage = fraction of games where we made a pick.
    """

    y_true_margin = np.asarray(y_true_margin, dtype=float)
    pred_margin = np.asarray(pred_margin, dtype=float)

    true_pick = (y_true_margin > 0).astype(float)  # home win = 1
    pred_pick = picks_from_margin(pred_margin, policy)

    mask = ~np.isnan(pred_pick)
    if mask.sum() == 0:
        return {"win_acc": float("nan"), "coverage": 0.0}

    win_acc = float((pred_pick[mask] == true_pick[mask]).mean())
    coverage = float(mask.mean())
    return {"win_acc": win_acc, "coverage": coverage}

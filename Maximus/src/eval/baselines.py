from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class MarginBaselines:
    zero: float
    hca: float


def estimate_hca_from_dev(y_dev_margin: np.ndarray) -> float:
    # mean of margin is the average home advantage in points
    return float(np.mean(y_dev_margin))


def predict_margin_zero(n: int) -> np.ndarray:
    return np.zeros(n, dtype=float)


def predict_margin_constant(n: int, value: float) -> np.ndarray:
    return np.full(n, value, dtype=float)


def predict_total_constant(n: int, value: float) -> np.ndarray:
    return np.full(n, value, dtype=float)


def estimate_total_mean_from_dev(y_dev_total: np.ndarray) -> float:
    return float(np.mean(y_dev_total))

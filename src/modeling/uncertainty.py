"""Uncertainty estimation utilities."""

from __future__ import annotations

import math
from typing import Iterable, Tuple

# 80% confidence interval z-score
Z80 = 1.2815515655446004


def clamp_sigma(sigma: float, *, min_sigma: float = 0.01) -> float:
    """Clamp sigma to a minimum value."""
    try:
        s = float(sigma)
    except Exception:
        s = min_sigma
    if not math.isfinite(s) or s <= 0:
        return min_sigma
    return max(min_sigma, s)


def normal_pi80(mu: float, sigma: float) -> Tuple[float, float]:
    """Calculate 80% prediction interval (q10, q90) for normal distribution."""
    sigma = clamp_sigma(sigma)
    mu = float(mu)
    return (mu - Z80 * sigma, mu + Z80 * sigma)


def rmse(residuals: Iterable[float]) -> float:
    """Calculate root mean squared error."""
    vals = [float(r) for r in residuals]
    if not vals:
        return 1.0
    return math.sqrt(sum(r * r for r in vals) / len(vals))


def sigma_from_residuals(residuals: Iterable[float], *, min_sigma: float = 0.01) -> float:
    """Estimate sigma from residuals using RMSE."""
    return clamp_sigma(rmse(residuals), min_sigma=min_sigma)

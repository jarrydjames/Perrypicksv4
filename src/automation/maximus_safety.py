"""MAXIMUS safety checks.

Purpose: prevent obviously-broken inputs/outputs from generating absurdly
confident betting recommendations.

We keep this separate to stay DRY across:
- pregame_cycle (prediction + bet storage)
- maximus_daily_summary (best-bets recompute)

Zen puppy rules:
- explicit > implicit
- log why we skipped
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class SafetyConfig:
    # Feature bounds (very conservative)
    efg_min: float = 0.42
    efg_max: float = 0.66
    ftr_min: float = 0.10
    ftr_max: float = 0.45
    tpar_min: float = 0.15
    tpar_max: float = 0.60
    tor_min: float = 0.07
    tor_max: float = 0.20
    orbp_min: float = 0.15
    orbp_max: float = 0.40

    # Prediction sanity
    total_min: float = 170.0
    total_max: float = 245.0
    margin_abs_max: float = 20.0

    # If clamping happens, allow betting only if it's small.
    max_clamped_features: int = 2


def safety_config_from_env() -> SafetyConfig:
    def f(name: str, default: float) -> float:
        try:
            return float(os.environ.get(name, str(default)))
        except Exception:
            return float(default)

    def i(name: str, default: int) -> int:
        try:
            return int(float(os.environ.get(name, str(default))))
        except Exception:
            return int(default)

    return SafetyConfig(
        efg_min=f("MAXIMUS_EFG_MIN", SafetyConfig.efg_min),
        efg_max=f("MAXIMUS_EFG_MAX", SafetyConfig.efg_max),
        ftr_min=f("MAXIMUS_FTR_MIN", SafetyConfig.ftr_min),
        ftr_max=f("MAXIMUS_FTR_MAX", SafetyConfig.ftr_max),
        tpar_min=f("MAXIMUS_TPAR_MIN", SafetyConfig.tpar_min),
        tpar_max=f("MAXIMUS_TPAR_MAX", SafetyConfig.tpar_max),
        tor_min=f("MAXIMUS_TOR_MIN", SafetyConfig.tor_min),
        tor_max=f("MAXIMUS_TOR_MAX", SafetyConfig.tor_max),
        orbp_min=f("MAXIMUS_ORBP_MIN", SafetyConfig.orbp_min),
        orbp_max=f("MAXIMUS_ORBP_MAX", SafetyConfig.orbp_max),
        total_min=f("MAXIMUS_TOTAL_MIN", SafetyConfig.total_min),
        total_max=f("MAXIMUS_TOTAL_MAX", SafetyConfig.total_max),
        margin_abs_max=f("MAXIMUS_MARGIN_ABS_MAX", SafetyConfig.margin_abs_max),
        max_clamped_features=i(
            "MAXIMUS_MAX_CLAMPED_FEATURES", SafetyConfig.max_clamped_features
        ),
    )


def clamp_features(
    feats: Dict[str, float], *, cfg: SafetyConfig
) -> Tuple[Dict[str, float], Dict[str, Tuple[float, float, float]]]:
    """Clamp feature values into sane bounds.

    Returns:
      (clamped_features, clamped_info)

    clamped_info maps key -> (old, new, (min,max) packed as new? nope) .
    We'll store (old, new, bound_min, bound_max) as a tuple.
    """

    bounds = {
        "efg": (cfg.efg_min, cfg.efg_max),
        "ftr": (cfg.ftr_min, cfg.ftr_max),
        "tpar": (cfg.tpar_min, cfg.tpar_max),
        "tor": (cfg.tor_min, cfg.tor_max),
        "orbp": (cfg.orbp_min, cfg.orbp_max),
    }

    clamped: Dict[str, float] = dict(feats)
    info: Dict[str, Tuple[float, float, float, float]] = {}

    for k, v in feats.items():
        suffix = k.split("_")[-1]
        if suffix not in bounds:
            continue
        lo, hi = bounds[suffix]
        old = float(v)
        new = min(hi, max(lo, old))
        clamped[k] = new
        if abs(new - old) > 1e-12:
            info[k] = (old, new, lo, hi)

    return clamped, info


def prediction_is_sane(
    pred_total: float, pred_margin: float, *, cfg: SafetyConfig
) -> bool:
    if not (cfg.total_min <= float(pred_total) <= cfg.total_max):
        return False
    if abs(float(pred_margin)) > cfg.margin_abs_max:
        return False
    return True


def allow_betting_recs(
    *,
    pred_total: float,
    pred_margin: float,
    clamped_info: Dict[str, Tuple[float, float, float, float]],
    cfg: SafetyConfig,
) -> bool:
    if not prediction_is_sane(pred_total, pred_margin, cfg=cfg):
        return False
    if len(clamped_info) > cfg.max_clamped_features:
        return False
    return True

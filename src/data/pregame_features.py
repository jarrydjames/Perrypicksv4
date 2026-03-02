"""Pregame feature builder (minimal, leakage-safe).

This is intentionally boring:
- Uses only historical data strictly before game start.
- Defaults are conservative.

Goal: produce a dict compatible with `src.models.pregame.PregameModel.features`.

If the model expects more features than we compute here, that's OK: the model
already fills missing with 0.0. But we should compute the *important* ones.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict

import pandas as pd

from src.features.temporal_store import get_feature_store


@dataclass(frozen=True)
class PregameFeatureContext:
    game_id: str
    home_tricode: str
    away_tricode: str
    game_datetime: datetime


def build_pregame_features(ctx: PregameFeatureContext) -> Dict[str, float]:
    """Build pregame feature dict for MAXIMUS models.

    Current pregame champion models in v5 expect ONLY 10 features:
    - home/away: efg, ftr, tpar, tor, orbp (all as proportions 0-1)

    We source these from the TemporalFeatureStore (same store used for REPTAR)
    using the most recent pregame-available snapshot prior to tip.
    """

    store = get_feature_store()

    target_dt = pd.Timestamp(ctx.game_datetime)
    if target_dt.tzinfo is None:
        target_dt = target_dt.tz_localize("UTC")
    else:
        target_dt = target_dt.tz_convert("UTC")
    home = store.get_team_features_by_tricode(ctx.home_tricode.upper(), target_dt, "home")
    away = store.get_team_features_by_tricode(ctx.away_tricode.upper(), target_dt, "away")

    def pick(src: Dict[str, float], key: str, default: float) -> float:
        v = src.get(key, default)
        try:
            return float(v)
        except Exception:
            return float(default)

    feats: Dict[str, float] = {
        "home_efg": pick(home, "home_efg", 0.52),
        "home_ftr": pick(home, "home_ftr", 0.25),
        "home_tpar": pick(home, "home_tpar", 0.35),
        "home_tor": pick(home, "home_tor", 0.12),
        "home_orbp": pick(home, "home_orbp", 0.25),
        "away_efg": pick(away, "away_efg", 0.52),
        "away_ftr": pick(away, "away_ftr", 0.25),
        "away_tpar": pick(away, "away_tpar", 0.35),
        "away_tor": pick(away, "away_tor", 0.12),
        "away_orbp": pick(away, "away_orbp", 0.25),
    }

    return feats


__all__ = [
    "PregameFeatureContext",
    "build_pregame_features",
]

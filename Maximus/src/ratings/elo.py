from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np
import pandas as pd
from pandas import DataFrame


@dataclass(frozen=True)
class EloConfig:
    initial_elo: float = 1500.0
    k_factor: float = 20.0
    home_advantage: float = 65.0  # Elo points


def expected_score(elo_a: float, elo_b: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / 400.0))


def update_elo(elo_home: float, elo_away: float, home_win: int, cfg: EloConfig) -> Tuple[float, float]:
    # apply home advantage to home team rating
    elo_home_adj = elo_home + cfg.home_advantage

    exp_home = expected_score(elo_home_adj, elo_away)
    score_home = float(home_win)
    delta = cfg.k_factor * (score_home - exp_home)

    return elo_home + delta, elo_away - delta


def compute_elo_features(games: DataFrame, cfg: EloConfig) -> DataFrame:
    """Compute pregame Elo features sequentially.

    IMPORTANT:
    - For each row (game), we emit the Elo ratings BEFORE updating with that game's result.
    - Then we update team Elos after the game.

    Required columns: home_tri, away_tri, home_pts, away_pts
    """

    elos: Dict[str, float] = {}

    out_rows = []
    for _, row in games.iterrows():
        home = row["home_tri"]
        away = row["away_tri"]

        home_elo = elos.get(home, cfg.initial_elo)
        away_elo = elos.get(away, cfg.initial_elo)

        out_rows.append(
            {
                "game_id": row["game_id"],
                "home_elo": home_elo,
                "away_elo": away_elo,
                "elo_diff": home_elo - away_elo,
            }
        )

        # update after game using final score (target)
        home_win = int(row["home_pts"] > row["away_pts"])
        new_home, new_away = update_elo(home_elo, away_elo, home_win, cfg)
        elos[home] = new_home
        elos[away] = new_away

    return pd.DataFrame(out_rows)

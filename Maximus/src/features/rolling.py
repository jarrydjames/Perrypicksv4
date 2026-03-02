from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd
from pandas import DataFrame


@dataclass(frozen=True)
class RollingConfig:
    windows: tuple[int, ...] = (5, 10, 20)


def team_game_rows(games: DataFrame) -> DataFrame:
    """Create per-team rows for rolling features.

    For each game we create two rows:
    - team=home, opp=away, is_home=1, pf=home_pts, pa=away_pts, margin=home_pts-away_pts
    - team=away, opp=home, is_home=0, pf=away_pts, pa=home_pts, margin=away_pts-home_pts

    IMPORTANT: This uses postgame scores ONLY to update historical state for FUTURE games.
    Rolling features for a game are computed using rows strictly before that game.
    """

    home_rows = pd.DataFrame(
        {
            "game_id": games["game_id"],
            "game_date": games["game_date"],
            "team": games["home_tri"],
            "opp": games["away_tri"],
            "is_home": 1,
            "pf": games["home_pts"],
            "pa": games["away_pts"],
        }
    )
    away_rows = pd.DataFrame(
        {
            "game_id": games["game_id"],
            "game_date": games["game_date"],
            "team": games["away_tri"],
            "opp": games["home_tri"],
            "is_home": 0,
            "pf": games["away_pts"],
            "pa": games["home_pts"],
        }
    )

    team_rows = pd.concat([home_rows, away_rows], ignore_index=True)
    team_rows["margin"] = team_rows["pf"] - team_rows["pa"]
    team_rows["total"] = team_rows["pf"] + team_rows["pa"]
    team_rows["win"] = (team_rows["margin"] > 0).astype(int)
    team_rows = team_rows.sort_values(["team", "game_date", "game_id"]).reset_index(drop=True)
    return team_rows


def build_team_rolling_features(games: DataFrame, cfg: RollingConfig) -> DataFrame:
    """Build rolling stats per team, joined back to games as home_/away_ features.

    Output has one row per game_id with features like:
    - home_margin_last5_mean, home_total_last5_mean, home_margin_last5_std, ...
    - away_margin_last5_mean, ...

    All rolling values are computed using ONLY prior games for that team.
    """

    tr = team_game_rows(games)

    feats = []
    for window in cfg.windows:
        g = tr.groupby("team", sort=False)

        # shift(1) ensures current game's outcome not included
        margin_roll = g["margin"].shift(1).rolling(window, min_periods=1)
        total_roll = g["total"].shift(1).rolling(window, min_periods=1)
        win_roll = g["win"].shift(1).rolling(window, min_periods=1)

        tr[f"margin_last{window}_mean"] = margin_roll.mean().to_numpy()
        tr[f"margin_last{window}_std"] = margin_roll.std(ddof=0).fillna(0.0).to_numpy()
        tr[f"total_last{window}_mean"] = total_roll.mean().to_numpy()
        tr[f"total_last{window}_std"] = total_roll.std(ddof=0).fillna(0.0).to_numpy()
        tr[f"win_last{window}_pct"] = win_roll.mean().fillna(0.0).to_numpy()

    # split into home/away side and merge
    home = tr[tr["is_home"] == 1].copy()
    away = tr[tr["is_home"] == 0].copy()

    drop_cols = ["team", "opp", "is_home", "pf", "pa", "margin", "total", "win", "game_date"]

    home = home.drop(columns=drop_cols)
    away = away.drop(columns=drop_cols)

    home = home.rename(columns={c: f"home_{c}" for c in home.columns if c != "game_id"})
    away = away.rename(columns={c: f"away_{c}" for c in away.columns if c != "game_id"})

    out = games[["game_id"]].merge(home, on="game_id", how="left").merge(away, on="game_id", how="left")

    # diff features for symmetry
    for window in cfg.windows:
        out[f"margin_last{window}_mean_diff"] = out[f"home_margin_last{window}_mean"] - out[
            f"away_margin_last{window}_mean"
        ]
        out[f"win_last{window}_pct_diff"] = out[f"home_win_last{window}_pct"] - out[
            f"away_win_last{window}_pct"
        ]

    return out

from __future__ import annotations

import pandas as pd
from pandas import DataFrame

from Maximus.src.features.rolling import RollingConfig, build_team_rolling_features
from Maximus.src.features.schedule import build_rest_features
from Maximus.src.features.sos import compute_sos_last_n
from Maximus.src.ratings.elo import EloConfig, compute_elo_features


def build_pregame_features(games: DataFrame) -> tuple[DataFrame, DataFrame]:
    """Build full pregame feature set.

    Returns:
        features_df: rows keyed by game_id
        elo_df: elo snapshot per game_id
    """

    # Elo
    elo_df = compute_elo_features(games, EloConfig())

    # Rolling recent form
    roll_df = build_team_rolling_features(games, RollingConfig(windows=(5, 10, 20)))

    # Rest/schedule features
    rest_df = build_rest_features(games)

    # SOS using Elo
    sos10_df = compute_sos_last_n(games, elo_df, window=10)

    # Join all
    feats = games[["game_id"]].merge(elo_df, on="game_id", how="left")
    feats = feats.merge(roll_df, on="game_id", how="left")
    feats = feats.merge(rest_df, on="game_id", how="left")
    feats = feats.merge(sos10_df, on="game_id", how="left")

    # Sanity: no NaNs (fill with neutral defaults)
    feats = feats.fillna(0.0)

    return feats, elo_df

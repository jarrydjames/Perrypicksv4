from __future__ import annotations

import pandas as pd
from pandas import DataFrame

from Maximus.src.paths import data_raw_dir
from Maximus.src.schema import REQUIRED_GAME_COLS


def load_historical_games() -> DataFrame:
    path = data_raw_dir() / "historical_games_full.parquet"
    df = pd.read_parquet(path)

    missing = [c for c in REQUIRED_GAME_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"historical_games missing columns: {missing}")

    # Normalize dtypes
    df = df.copy()
    df["game_id"] = df["game_id"].astype(str)
    df["home_tri"] = df["home_tri"].astype(str)
    df["away_tri"] = df["away_tri"].astype(str)
    df["season"] = df["season"].astype(str)
    df["game_date"] = pd.to_datetime(df["game_date"], utc=True, errors="raise")

    # Ensure strict chronological order
    df = df.sort_values(["game_date", "game_id"], ascending=True).reset_index(drop=True)
    return df

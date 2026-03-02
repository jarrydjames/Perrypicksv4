from __future__ import annotations

import pandas as pd
from pandas import DataFrame


def build_rest_features(games: DataFrame) -> DataFrame:
    """Compute rest days + back-to-back flags from prior game dates.

    This uses ONLY schedule info implicitly present in historical games.
    For each team and game, rest_days = days since team's previous game.

    All features are computed from dates strictly before the current game.
    """

    games = games[["game_id", "game_date", "home_tri", "away_tri"]].copy()

    # Build per-team game list
    rows = []
    for side in ["home", "away"]:
        tri_col = f"{side}_tri"
        tmp = games[["game_id", "game_date", tri_col]].rename(columns={tri_col: "team"})
        tmp["side"] = side
        rows.append(tmp)

    tg = pd.concat(rows, ignore_index=True)
    tg = tg.sort_values(["team", "game_date", "game_id"]).reset_index(drop=True)

    # previous game date per team (strictly before current)
    tg["prev_game_date"] = tg.groupby("team")["game_date"].shift(1)
    tg["rest_days"] = (tg["game_date"] - tg["prev_game_date"]).dt.total_seconds() / (3600 * 24)
    tg["rest_days"] = tg["rest_days"].fillna(7.0)  # early season unknown -> treat as rested
    tg["b2b"] = (tg["rest_days"] <= 1.5).astype(int)

    # games played last 7/14 days (count prior games)
    for days in [7, 14]:
        # rolling count of games in prior window
        # We'll do it per-team with expanding window via searchsorted.
        out_counts = []
        for team, grp in tg.groupby("team", sort=False):
            dates = grp["game_date"].to_numpy()
            counts = []
            for i, d in enumerate(dates):
                # count prior dates within [d-days, d)
                start = d - pd.Timedelta(days=days)
                # searchsorted on numpy datetime64
                left = dates.searchsorted(start, side="left")
                right = i  # exclude current game
                counts.append(max(0, right - left))
            out_counts.extend(counts)
        tg[f"games_last{days}"] = out_counts

    home = tg[tg["side"] == "home"][["game_id", "rest_days", "b2b", "games_last7", "games_last14"]]
    away = tg[tg["side"] == "away"][["game_id", "rest_days", "b2b", "games_last7", "games_last14"]]

    home = home.rename(
        columns={
            "rest_days": "rest_days_home",
            "b2b": "b2b_home",
            "games_last7": "games_last7_home",
            "games_last14": "games_last14_home",
        }
    )
    away = away.rename(
        columns={
            "rest_days": "rest_days_away",
            "b2b": "b2b_away",
            "games_last7": "games_last7_away",
            "games_last14": "games_last14_away",
        }
    )

    out = games[["game_id"]].merge(home, on="game_id", how="left").merge(away, on="game_id", how="left")
    out["rest_diff"] = out["rest_days_home"] - out["rest_days_away"]
    out["b2b_diff"] = out["b2b_home"] - out["b2b_away"]
    out["games_last7_diff"] = out["games_last7_home"] - out["games_last7_away"]
    out["games_last14_diff"] = out["games_last14_home"] - out["games_last14_away"]

    return out

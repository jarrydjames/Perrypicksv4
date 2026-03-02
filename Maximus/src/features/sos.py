from __future__ import annotations

import pandas as pd
from pandas import DataFrame


def compute_sos_last_n(games: DataFrame, elo_snapshots: DataFrame, window: int = 10) -> DataFrame:
    """Compute strength-of-schedule features using opponent Elo pregame snapshots.

    SOS for a team at game i is the mean opponent Elo over the last N games
    (strictly prior games), using the opponent's Elo *at that time*.

    Implementation note:
    - We derive per-team rows and use shift(1) rolling(window).
    """

    base = games[["game_id", "game_date", "home_tri", "away_tri"]].merge(
        elo_snapshots[["game_id", "home_elo", "away_elo"]], on="game_id", how="left"
    )

    # Build per-team rows with opponent elo at time of match
    home = pd.DataFrame(
        {
            "game_id": base["game_id"],
            "game_date": base["game_date"],
            "team": base["home_tri"],
            "opp_elo": base["away_elo"],
            "side": "home",
        }
    )
    away = pd.DataFrame(
        {
            "game_id": base["game_id"],
            "game_date": base["game_date"],
            "team": base["away_tri"],
            "opp_elo": base["home_elo"],
            "side": "away",
        }
    )

    tr = pd.concat([home, away], ignore_index=True)
    tr = tr.sort_values(["team", "game_date", "game_id"]).reset_index(drop=True)

    g = tr.groupby("team", sort=False)
    roll = g["opp_elo"].shift(1).rolling(window, min_periods=1)
    tr[f"sos_last{window}"] = roll.mean().to_numpy()

    home_s = tr[tr["side"] == "home"][["game_id", f"sos_last{window}"]].rename(
        columns={f"sos_last{window}": f"home_sos_last{window}"}
    )
    away_s = tr[tr["side"] == "away"][["game_id", f"sos_last{window}"]].rename(
        columns={f"sos_last{window}": f"away_sos_last{window}"}
    )

    out = games[["game_id"]].merge(home_s, on="game_id", how="left").merge(away_s, on="game_id", how="left")
    out[f"sos_last{window}_diff"] = out[f"home_sos_last{window}"] - out[f"away_sos_last{window}"]
    return out

"""MAXIMUS (v5/Maximus) feature builder for production.

This produces the exact 54-feature vector used to train the CatBoost deploy
models located in `Maximus/models/`.

Training truth:
- `Maximus/data/processed/features.parquet` defines the feature column order.
- Deploy models were trained on `X = df[feature_cols].to_numpy()`.

Runtime strategy (simple + leakage-safe):
- Load Maximus historical games parquet (already in-repo).
- Filter to games strictly BEFORE the target tip datetime.
- Append a single future row for the matchup (no outcome).
- Run the Maximus feature pipeline; use the generated row for that future game.

This keeps feature engineering identical to training without duplicating logic.

Note:
- This assumes teams exist in the historical parquet and there is enough history.
- If feature generation fails, callers should fall back.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pandas as pd


MAXIMUS_ROOT = Path(__file__).resolve().parents[2] / "Maximus"


@dataclass(frozen=True)
class MaximusFeatureContext:
    game_id: str
    home_tricode: str
    away_tricode: str
    game_datetime_utc: datetime
    season: str


def maximus_feature_columns() -> List[str]:
    feats_path = MAXIMUS_ROOT / "data" / "processed" / "features.parquet"
    df = pd.read_parquet(feats_path)
    return [c for c in df.columns if c != "game_id"]


def _load_historical_games() -> pd.DataFrame:
    """Load Maximus historical games and extend with newer FINAL games from v5 DB."""

    from Maximus.src.data.load_raw import load_historical_games

    base = load_historical_games()

    # Append any newer FINAL games from the v5 DB so rolling/Elo is current.
    try:
        from dashboard.backend.database import SessionLocal, Game

        max_dt = base["game_date"].max()

        db = SessionLocal()
        try:
            rows = (
                db.query(Game)
                .filter(Game.game_status.ilike("%final%"))
                .filter(Game.final_home_score.isnot(None), Game.final_away_score.isnot(None))
                .all()
            )

            add = []
            for g in rows:
                if not g.nba_id or not g.game_date:
                    continue
                # interpret DB game_date naive as UTC (it is stored as league-local; however
                # Maximus historical uses midnight UTC per day, so this is an approximation.
                # We only need ordering; exact time-of-day is not critical for rolling windows.
                dt = pd.to_datetime(g.game_date, utc=True, errors="coerce")
                if dt is pd.NaT:
                    continue
                if max_dt is not None and dt <= max_dt:
                    continue

                # infer season
                season = season_str_from_dt(dt.to_pydatetime())

                add.append(
                    {
                        "game_id": str(g.nba_id),
                        "game_date": dt,
                        "season": season,
                        "home_tri": str(g.home_team).upper(),
                        "away_tri": str(g.away_team).upper(),
                        "home_pts": float(g.final_home_score or 0.0),
                        "away_pts": float(g.final_away_score or 0.0),
                        "margin": float((g.final_home_score or 0.0) - (g.final_away_score or 0.0)),
                        "total": float((g.final_home_score or 0.0) + (g.final_away_score or 0.0)),
                    }
                )

            if add:
                extra = pd.DataFrame(add)
                extra["game_date"] = pd.to_datetime(extra["game_date"], utc=True)
                base = pd.concat([base, extra], ignore_index=True)
                base = base.sort_values(["game_date", "game_id"], ascending=True).reset_index(drop=True)
        finally:
            db.close()
    except Exception:
        # fail-soft: base historical parquet is still usable
        pass

    return base


def season_str_from_dt(dt_utc: datetime) -> str:
    """Infer NBA season label like '2025-26' from a UTC datetime."""
    y = int(dt_utc.year)
    m = int(dt_utc.month)
    if m >= 10:
        return f"{y}-{str(y+1)[-2:]}"
    return f"{y-1}-{str(y)[-2:]}"


def build_maximus_features(ctx: MaximusFeatureContext) -> Dict[str, float]:
    """Build 54 Maximus features for one upcoming matchup."""

    from Maximus.src.features.build_features import build_pregame_features

    games = _load_historical_games()

    # Strictly before tip (leakage guard)
    tip = pd.to_datetime(ctx.game_datetime_utc, utc=True)
    games_hist = games[games["game_date"] < tip].copy()

    # Append future row
    future = pd.DataFrame(
        [
            {
                "game_id": str(ctx.game_id),
                "game_date": tip,
                "season": str(ctx.season),
                "home_tri": str(ctx.home_tricode).upper(),
                "away_tri": str(ctx.away_tricode).upper(),
                # Unknown pre-tip outcomes: set 0.
                # These columns are REQUIRED by schema but are NOT used as features.
                "home_pts": 0.0,
                "away_pts": 0.0,
                "margin": 0.0,
                "total": 0.0,
            }
        ]
    )

    combined = pd.concat([games_hist, future], ignore_index=True)
    combined = combined.sort_values(["game_date", "game_id"], ascending=True).reset_index(drop=True)

    feats_df, _elo_df = build_pregame_features(combined)

    # Get feature row for the future game_id
    row = feats_df[feats_df["game_id"].astype(str) == str(ctx.game_id)]
    if row.empty:
        raise RuntimeError(f"Maximus feature pipeline produced no row for game_id={ctx.game_id}")

    row = row.iloc[0]
    cols = maximus_feature_columns()

    out: Dict[str, float] = {}
    for c in cols:
        v = row.get(c, 0.0)
        try:
            out[c] = float(v)
        except Exception:
            out[c] = 0.0

    return out


__all__ = [
    "MaximusFeatureContext",
    "maximus_feature_columns",
    "season_str_from_dt",
    "build_maximus_features",
]

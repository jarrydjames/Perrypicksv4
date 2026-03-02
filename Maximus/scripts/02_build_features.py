"""Build Maximus pregame features (strict prior-only) and write processed dataset.

Outputs:
- Maximus/data/processed/games.parquet (normalized games)
- Maximus/data/processed/features.parquet (features keyed by game_id)
- Maximus/data/processed/model_matrix.parquet (games + features + targets)
- Maximus/data/ratings/elo_snapshots.parquet

Also writes:
- Maximus/reports/FEATURE_CATALOG.md
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from Maximus.src.data.load_raw import load_historical_games
from Maximus.src.features.build_features import build_pregame_features
from Maximus.src.paths import artifacts_dir, data_processed_dir, data_ratings_dir, reports_dir
from Maximus.src.utils_hashing import sha256_file


def main() -> int:
    games = load_historical_games()

    feats, elo = build_pregame_features(games)

    out_dir = data_processed_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    data_ratings_dir().mkdir(parents=True, exist_ok=True)
    artifacts_dir().mkdir(parents=True, exist_ok=True)
    reports_dir().mkdir(parents=True, exist_ok=True)

    games_path = out_dir / "games.parquet"
    feats_path = out_dir / "features.parquet"
    matrix_path = out_dir / "model_matrix.parquet"
    elo_path = data_ratings_dir() / "elo_snapshots.parquet"

    games.to_parquet(games_path, index=False)
    feats.to_parquet(feats_path, index=False)
    elo.to_parquet(elo_path, index=False)

    matrix = games.merge(feats, on="game_id", how="left")
    matrix.to_parquet(matrix_path, index=False)

    hashes = {
        "games": {"path": str(games_path), "sha256": sha256_file(games_path)},
        "features": {"path": str(feats_path), "sha256": sha256_file(feats_path)},
        "model_matrix": {"path": str(matrix_path), "sha256": sha256_file(matrix_path)},
        "elo": {"path": str(elo_path), "sha256": sha256_file(elo_path)},
    }

    (artifacts_dir() / "FEATURE_BUILD_MANIFEST.json").write_text(
        json.dumps(
            {
                "step": "02_build_features",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "hashes": hashes,
                "n_games": int(len(games)),
                "n_features": int(feats.shape[1] - 1),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # Feature catalog (explicit, audit-friendly)
    feature_catalog = reports_dir() / "FEATURE_CATALOG.md"
    feature_cols = [c for c in feats.columns if c != "game_id"]

    blocks = {
        "elo": ["home_elo", "away_elo", "elo_diff"],
        "schedule": [
            "rest_days_home",
            "rest_days_away",
            "rest_diff",
            "b2b_home",
            "b2b_away",
            "b2b_diff",
            "games_last7_home",
            "games_last7_away",
            "games_last7_diff",
            "games_last14_home",
            "games_last14_away",
            "games_last14_diff",
        ],
        "sos": ["home_sos_last10", "away_sos_last10", "sos_last10_diff"],
        "recent_form": [c for c in feature_cols if "last" in c and c not in {"home_sos_last10","away_sos_last10"}],
    }

    lines = [
        "# Feature Catalog (Maximus)",
        "",
        "All features are computed strictly from data with timestamp < game_date.",
        "",
        "## Data sources",
        "- Maximus/data/raw/historical_games_full.parquet (game schedule + final scores used ONLY to update prior-game history)",
        "",
        f"Total features: {len(feature_cols)}",
        "",
        "## Timing rule",
        "For a game at time D, every feature must be computed using only games with game_date < D.",
        "Implementation: all rolling windows use shift(1) before rolling; Elo snapshots are taken before update.",
        "",
    ]

    def emit(name: str, feats_list: list[str], definition: str) -> None:
        lines.append(f"## Block: {name}")
        lines.append(definition)
        lines.append("")
        for c in sorted(set(feats_list)):
            if c in feature_cols:
                lines.append(f"- `{c}`")
        lines.append("")

    emit(
        "Elo",
        blocks["elo"],
        "Definition: sequential Elo ratings computed game-by-game. Features are Elo BEFORE the current game is played.",
    )
    emit(
        "Schedule / Rest",
        blocks["schedule"],
        "Definition: rest and workload inferred from each team's prior game dates. Rest is days since previous game; B2B if rest<=1.5 days. games_last7/14 counts prior games in that window.",
    )
    emit(
        "Strength of Schedule (SOS)",
        blocks["sos"],
        "Definition: mean opponent Elo over the last 10 games (prior-only), using opponent's Elo snapshot at those times.",
    )
    emit(
        "Recent Form (Rolling)",
        blocks["recent_form"],
        "Definition: team rolling statistics over last 5/10/20 prior games: margin mean/std, total mean/std, win%.",
    )

    feature_catalog.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote processed datasets to: {out_dir}")
    print(f"Wrote feature catalog: {feature_catalog}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

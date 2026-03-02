"""Create locked splits + CV folds.

Outputs:
- Maximus/artifacts/SPLITS.json

This is a LOCKED split spec. Do not regenerate casually.
"""

from __future__ import annotations

from Maximus.src.data.load_raw import load_historical_games
from Maximus.src.eval.splits import make_locked_splits
from Maximus.src.paths import artifacts_dir


def main() -> int:
    artifacts_dir().mkdir(parents=True, exist_ok=True)

    games = load_historical_games()

    # Split regime:
    # - Dev universe: seasons 2022-23, 2023-24, 2024-25
    # - Holdout: last 500 games within dev universe
    # - Future block: all 2025-26 games (stress test only)
    dev_seasons = {"2022-23", "2023-24", "2024-25"}
    future_season = "2025-26"

    dev_mask = games["season"].astype(str).isin(dev_seasons)
    future_mask = games["season"].astype(str).eq(future_season)

    dev_universe = games[dev_mask].reset_index(drop=False)  # keep original index
    future_block = games[future_mask].reset_index(drop=False)

    if len(future_block) == 0:
        raise RuntimeError("No 2025-26 games found; cannot create future block")

    # Create splits inside dev universe
    spec_dev = make_locked_splits(dev_universe, holdout_size=500, min_train_size=1000, test_block_size=50)

    # Map indices back to original games index space
    dev_indices = dev_universe.loc[spec_dev.dev_indices, "index"].astype(int).tolist()
    holdout_indices = dev_universe.loc[spec_dev.holdout_indices, "index"].astype(int).tolist()
    future_indices = future_block["index"].astype(int).tolist()

    game_ids = games["game_id"].astype(str).tolist()

    payload = {
        "split_regime": {
            "dev_seasons": sorted(dev_seasons),
            "future_season": future_season,
            "holdout_size": 500,
            "min_train_size": 1000,
            "test_block_size": 50,
        },
        "dev_indices": dev_indices,
        "holdout_indices": holdout_indices,
        "future_indices": future_indices,
        "dev_game_ids": [game_ids[i] for i in dev_indices],
        "holdout_game_ids": [game_ids[i] for i in holdout_indices],
        "future_game_ids": [game_ids[i] for i in future_indices],
        "cv_folds": [
            {
                # IMPORTANT:
                # - train_indices/test_indices are in DEV-LOCAL index space (0..len(dev)-1)
                #   so they can be used directly with X_dev/y_dev.
                # - we also store *_global_indices and *_game_ids for auditability.
                "train_indices": f["train_indices"],
                "test_indices": f["test_indices"],
                "train_global_indices": dev_universe.loc[f["train_indices"], "index"].astype(int).tolist(),
                "test_global_indices": dev_universe.loc[f["test_indices"], "index"].astype(int).tolist(),
                "train_game_ids": [
                    game_ids[i]
                    for i in dev_universe.loc[f["train_indices"], "index"].astype(int).tolist()
                ],
                "test_game_ids": [
                    game_ids[i]
                    for i in dev_universe.loc[f["test_indices"], "index"].astype(int).tolist()
                ],
            }
            for f in spec_dev.cv_folds
        ],
    }

    out_path = artifacts_dir() / "SPLITS.json"
    out_path.write_text(__import__("json").dumps(payload, indent=2), encoding="utf-8")

    print(f"Wrote: {out_path}")
    print(f"Dev size: {len(spec_dev.dev_indices)}")
    print(f"Holdout size: {len(spec_dev.holdout_indices)}")
    print(f"CV folds: {len(spec_dev.cv_folds)}")
    print(f"Future size: {len(future_indices)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

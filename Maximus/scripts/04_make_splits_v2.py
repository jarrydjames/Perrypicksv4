"""Create locked splits for Protocol V2.

Outputs:
- Maximus/artifacts/SPLITS_V2.json

V2 does NOT overwrite SPLITS.json.
"""

from __future__ import annotations

from Maximus.src.data.load_raw import load_historical_games

import pandas as pd
from Maximus.src.eval.splits import make_locked_splits
from Maximus.src.paths import artifacts_dir


def main() -> int:
    artifacts_dir().mkdir(parents=True, exist_ok=True)

    games = load_historical_games()

    dev_seasons = {"2022-23", "2023-24", "2024-25"}
    future_season = "2025-26"

    dev_mask = games["season"].astype(str).isin(dev_seasons)
    future_mask = games["season"].astype(str).eq(future_season)

    dev_universe = games[dev_mask].reset_index(drop=False)
    future_block = games[future_mask].reset_index(drop=False)

    if len(future_block) == 0:
        raise RuntimeError("No 2025-26 games found; cannot create future block")

    spec_dev = make_locked_splits(dev_universe, holdout_size=500, min_train_size=1000, test_block_size=50)

    dev_indices = dev_universe.loc[spec_dev.dev_indices, "index"].astype(int).tolist()
    holdout_indices = dev_universe.loc[spec_dev.holdout_indices, "index"].astype(int).tolist()
    # Split 2025-26 into a truly-locked final test window (most recent) + optional shadow.
    # Rigor principle: never use the final window for tuning/iteration.
    future_block = future_block.sort_values(["game_date", "game_id"], ascending=True)

    max_fut_date = pd.to_datetime(future_block["game_date"].max(), utc=True)
    test_start = max_fut_date - pd.Timedelta(days=30)

    fut_test = future_block[future_block["game_date"] >= test_start].copy()
    min_test_games = 100
    if len(fut_test) < min_test_games:
        fut_test = future_block.tail(min_test_games).copy()

    fut_shadow = future_block.drop(index=fut_test.index).copy()

    future_indices = fut_test["index"].astype(int).tolist()
    future_shadow_indices = fut_shadow["index"].astype(int).tolist()

    game_ids = games["game_id"].astype(str).tolist()

    payload = {
        "protocol": "V2",
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
        "future_shadow_indices": future_shadow_indices,
        "dev_game_ids": [game_ids[i] for i in dev_indices],
        "holdout_game_ids": [game_ids[i] for i in holdout_indices],
        "future_game_ids": [game_ids[i] for i in future_indices],
        "future_shadow_game_ids": [game_ids[i] for i in future_shadow_indices],
        "cv_folds": [
            {
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

    out_path = artifacts_dir() / "SPLITS_V2.json"
    out_path.write_text(__import__("json").dumps(payload, indent=2), encoding="utf-8")

    print(f"Wrote: {out_path}")
    print(f"Dev size: {len(spec_dev.dev_indices)}")
    print(f"Holdout size: {len(spec_dev.holdout_indices)}")
    print(f"CV folds: {len(spec_dev.cv_folds)}")
    print(f"Future TEST size (locked): {len(future_indices)}")
    print(f"Future SHADOW size: {len(future_shadow_indices)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

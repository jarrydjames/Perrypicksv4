from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
from pandas import DataFrame

from Maximus.src.schema import SplitSpec


def make_locked_splits(
    games: DataFrame,
    holdout_size: int = 500,
    min_train_size: int = 1000,
    test_block_size: int = 100,
) -> SplitSpec:
    """Create locked dev/holdout and walk-forward CV folds on dev.

    Assumes `games` already sorted chronologically by (game_date, game_id).
    """

    n = len(games)
    if n <= holdout_size + min_train_size + test_block_size:
        raise ValueError("Not enough games for requested split sizes")

    holdout_indices = list(range(n - holdout_size, n))
    dev_indices = list(range(0, n - holdout_size))

    n_dev = len(dev_indices)

    folds = []
    # expanding window CV on dev
    start_test = min_train_size
    while start_test + test_block_size <= n_dev:
        train_idx = list(range(0, start_test))
        test_idx = list(range(start_test, start_test + test_block_size))
        folds.append({"train_indices": train_idx, "test_indices": test_idx})
        start_test += test_block_size

    return SplitSpec(
        dev_indices=dev_indices,
        holdout_indices=holdout_indices,
        future_indices=[],
        future_shadow_indices=[],
        cv_folds=folds,
    )


def save_splits(spec: SplitSpec, path: Path) -> None:
    path.write_text(json.dumps(asdict(spec), indent=2), encoding="utf-8")


def load_splits(path: Path) -> SplitSpec:
    d = json.loads(path.read_text(encoding="utf-8"))
    # tolerate audit-friendly extra fields like *_game_ids
    return SplitSpec(
        dev_indices=d["dev_indices"],
        holdout_indices=d["holdout_indices"],
        future_indices=d.get("future_indices", []),
        future_shadow_indices=d.get("future_shadow_indices", []),
        cv_folds=d["cv_folds"],
    )

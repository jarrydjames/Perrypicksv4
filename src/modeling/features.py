"""Feature column handling for train/serve consistency."""

from __future__ import annotations

from typing import List, Set

import pandas as pd


# Columns to exclude from features (targets, IDs, metadata)
DEFAULT_IGNORE: Set[str] = {
    "game_id",
    "game_date",
    "season_end_yy",
    "home_tri",
    "away_tri",
    # Targets
    "h2_total",
    "h2_margin",
    "total",
    "margin",
    "home_score",
    "away_score",
    "final_total",
    "final_margin",
}


def get_feature_columns(df: pd.DataFrame, *, ignore: Set[str] | None = None) -> List[str]:
    """
    Get feature columns from dataframe in deterministic order.

    This function ensures train/serve skew is avoided by using
    the same feature selection logic everywhere.

    Args:
        df: DataFrame with features
        ignore: Additional columns to ignore

    Returns:
        Sorted list of feature column names
    """
    ig = set(DEFAULT_IGNORE)
    if ignore:
        ig |= set(ignore)

    cols = [c for c in df.columns if c not in ig]
    cols.sort()
    return cols

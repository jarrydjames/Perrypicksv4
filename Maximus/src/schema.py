from __future__ import annotations

from dataclasses import dataclass
from typing import Final


TARGET_MARGIN_COL: Final[str] = "margin"
TARGET_TOTAL_COL: Final[str] = "total"

REQUIRED_GAME_COLS: Final[tuple[str, ...]] = (
    "game_id",
    "game_date",
    "season",
    "home_tri",
    "away_tri",
    "home_pts",
    "away_pts",
    TARGET_MARGIN_COL,
    TARGET_TOTAL_COL,
)

PROHIBITED_FEATURE_SUBSTRINGS: Final[tuple[str, ...]] = (
    "home_pts",
    "away_pts",
    "margin",
    "total",
    "winner",
    "won",
)


@dataclass(frozen=True)
class SplitSpec:
    dev_indices: list[int]
    holdout_indices: list[int]

    # Most recent out-of-sample block (locked final test)
    future_indices: list[int]

    # Optional: earlier "future" data used only for monitoring/reporting.
    # Keep empty unless you are intentionally doing staged evaluation.
    future_shadow_indices: list[int]

    cv_folds: list[dict]

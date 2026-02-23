"""Core type definitions for the prediction system."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class Interval:
    """Confidence interval bounds."""
    low: float
    high: float


@dataclass(frozen=True)
class HeadPrediction:
    """Single head prediction with uncertainty."""
    mu: float
    sigma: float
    pi80: Interval


@dataclass(frozen=True)
class TrainedHead:
    """Trained model head with features and residual sigma."""
    features: List[str]
    model: Any
    residual_sigma: float


@dataclass(frozen=True)
class PredictionResult:
    """Standard prediction output."""
    game_id: str

    # Core predictions
    home_win_prob: float
    margin_mean: float
    margin_sd: float
    total_mean: float
    total_sd: float

    # 80% confidence intervals
    margin_q10: float
    margin_q90: float
    total_q10: float
    total_q90: float

    # Metadata
    model_name: str
    model_version: str
    feature_version: str


# Team ID mappings (NBA official IDs)
TEAM_ID_TO_TRICODE = {
    1610612737: 'ATL', 1610612738: 'BOS', 1610612751: 'BKN',
    1610612766: 'CHA', 1610612741: 'CHI', 1610612739: 'CLE',
    1610612742: 'DAL', 1610612743: 'DEN', 1610612765: 'DET',
    1610612744: 'GSW', 1610612745: 'HOU', 1610612754: 'IND',
    1610612746: 'LAC', 1610612747: 'LAL', 1610612763: 'MEM',
    1610612748: 'MIA', 1610612749: 'MIL', 1610612750: 'MIN',
    1610612740: 'NOP', 1610612752: 'NYK', 1610612760: 'OKC',
    1610612753: 'ORL', 1610612755: 'PHI', 1610612756: 'PHX',
    1610612757: 'POR', 1610612758: 'SAC', 1610612759: 'SAS',
    1610612761: 'TOR', 1610612762: 'UTA', 1610612764: 'WAS',
}

TRICODE_TO_TEAM_ID = {v: k for k, v in TEAM_ID_TO_TRICODE.items()}

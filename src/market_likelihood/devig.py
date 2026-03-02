from __future__ import annotations

from dataclasses import dataclass

from src.betting import implied_prob_from_american

from .types import FairProbabilities


def devig_two_sided(*, odds_a: int, odds_b: int) -> FairProbabilities:
    """Convert a two-sided American odds market to fair probabilities.

    Uses simple proportional de-vig:
      p_fair = p_raw / sum(p_raw)

    Assumes odds_a and odds_b correspond to opposite sides at the same line.
    """

    p_a_raw = float(implied_prob_from_american(int(odds_a)))
    p_b_raw = float(implied_prob_from_american(int(odds_b)))

    denom = p_a_raw + p_b_raw
    if denom <= 0:
        # Defensive fallback
        return FairProbabilities(p_side_a=0.5, p_side_b=0.5)

    p_a = p_a_raw / denom
    return FairProbabilities(p_side_a=p_a, p_side_b=1.0 - p_a)

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from .base import LikelihoodModel
from ..types import BetTicket, MarketSnapshot, ProbabilityEstimate


@dataclass(frozen=True)
class NormalMarginConfig:
    """Prototype config for Approach A.

    NOTE: We are intentionally not implementing the full math yet.
    This is a contract + placeholder.
    """

    # Fixed sigma defaults (placeholder values)
    sigma_spread: float = 12.0
    sigma_total: float = 14.0
    sigma_team_total: float = 10.0


class NormalMarginModel(LikelihoodModel):
    """Approach A (baseline): Normal approximation around market-implied mean."""

    def __init__(self, cfg: NormalMarginConfig | None = None):
        self._cfg = cfg or NormalMarginConfig()

    def estimate(
        self,
        *,
        ticket: BetTicket,
        snapshot: MarketSnapshot,
        history: Sequence[MarketSnapshot],
    ) -> ProbabilityEstimate:
        # TODO(v1): implement:
        # - devig
        # - infer mu from snapshot line
        # - choose sigma (fixed or volatility-based)
        # - compute p_hit for ORIGINAL ticket
        return ProbabilityEstimate(
            bet_id=ticket.bet_id,
            timestamp_utc=snapshot.timestamp_utc,
            p_hit=0.0,
            notes=("placeholder: NormalMarginModel not implemented",),
        )

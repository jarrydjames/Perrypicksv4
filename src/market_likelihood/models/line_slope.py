from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .base import LikelihoodModel
from ..types import BetTicket, MarketSnapshot, ProbabilityEstimate


@dataclass(frozen=True)
class LineSlopeConfig:
    min_points_movement: float = 1.0
    max_history: int = 30


class LineSlopeModel(LikelihoodModel):
    """Approach B: estimate dp/dL from recent market history and translate to ticket line."""

    def __init__(self, cfg: LineSlopeConfig | None = None):
        self._cfg = cfg or LineSlopeConfig()

    def estimate(
        self,
        *,
        ticket: BetTicket,
        snapshot: MarketSnapshot,
        history: Sequence[MarketSnapshot],
    ) -> ProbabilityEstimate:
        # TODO(v1): implement:
        # - build (line, fair_prob) pairs over history
        # - estimate slope near current line
        # - translate p(now) -> p(orig)
        return ProbabilityEstimate(
            bet_id=ticket.bet_id,
            timestamp_utc=snapshot.timestamp_utc,
            p_hit=0.0,
            notes=("placeholder: LineSlopeModel not implemented",),
        )

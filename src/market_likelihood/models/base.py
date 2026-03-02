from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from ..types import BetTicket, MarketSnapshot, ProbabilityEstimate


class LikelihoodModel(ABC):
    """Interface for translating live market snapshots into ticket likelihood."""

    @abstractmethod
    def estimate(
        self,
        *,
        ticket: BetTicket,
        snapshot: MarketSnapshot,
        history: Sequence[MarketSnapshot],
    ) -> ProbabilityEstimate:
        raise NotImplementedError

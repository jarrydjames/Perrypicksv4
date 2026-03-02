from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Sequence


class BetType(str, Enum):
    SPREAD = "spread"
    TOTAL = "total"
    TEAM_TOTAL = "team_total"


class BetSide(str, Enum):
    HOME = "home"
    AWAY = "away"
    OVER = "over"
    UNDER = "under"


class StatusTier(str, Enum):
    STRONG = "strong"
    OK = "ok"
    WATCH = "watch"
    DANGER = "danger"
    EXIT = "exit"


@dataclass(frozen=True)
class BetTicket:
    bet_id: str
    game_id: str
    bet_type: BetType
    side: BetSide
    line: float
    odds_american: int
    created_at_utc: datetime
    discord_message_id: Optional[str] = None


@dataclass(frozen=True)
class MarketSnapshot:
    game_id: str
    timestamp_utc: datetime
    bet_type: BetType
    line_current: float
    odds_side_a_american: int
    odds_side_b_american: int
    bookmaker: str


@dataclass(frozen=True)
class FairProbabilities:
    # Probability of side A and side B at the CURRENT line (vig removed)
    p_side_a: float
    p_side_b: float


@dataclass(frozen=True)
class ProbabilityBand:
    low: float
    high: float


@dataclass(frozen=True)
class ProbabilityEstimate:
    bet_id: str
    timestamp_utc: datetime
    p_hit: float
    band: Optional[ProbabilityBand] = None

    # Trend signals for UX
    delta_2m: Optional[float] = None
    momentum: Optional[float] = None

    tier: Optional[StatusTier] = None

    # Human-friendly explanation fields
    move_points_against_ticket: Optional[float] = None
    notes: Sequence[str] = ()

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Deque, Dict, Optional
from collections import deque

from .types import ProbabilityEstimate, StatusTier


@dataclass
class TierPolicy:
    strong: float = 0.70
    ok: float = 0.55
    watch: float = 0.40
    danger: float = 0.25
    exit: float = 0.00

    hysteresis_up: float = 0.05
    consecutive_down: int = 2


def tier_for_p(p: float, policy: TierPolicy) -> StatusTier:
    if p >= policy.strong:
        return StatusTier.STRONG
    if p >= policy.ok:
        return StatusTier.OK
    if p >= policy.watch:
        return StatusTier.WATCH
    if p >= policy.danger:
        return StatusTier.DANGER
    return StatusTier.EXIT


@dataclass
class BetState:
    bet_id: str
    history: Deque[ProbabilityEstimate] = field(default_factory=lambda: deque(maxlen=20))
    current_tier: Optional[StatusTier] = None
    _down_count: int = 0
    last_alert_at: Optional[datetime] = None


class StateTracker:
    """Tracks rolling probability history and applies hysteresis for tier changes."""

    def __init__(self, policy: TierPolicy | None = None, alert_cooldown: timedelta | None = None):
        self._policy = policy or TierPolicy()
        self._alert_cooldown = alert_cooldown or timedelta(minutes=5)
        self._bets: Dict[str, BetState] = {}

    def upsert(self, est: ProbabilityEstimate) -> BetState:
        st = self._bets.get(est.bet_id)
        if st is None:
            st = BetState(bet_id=est.bet_id)
            self._bets[est.bet_id] = st

        st.history.append(est)
        self._apply_tier(st)
        return st

    def should_alert(self, st: BetState, *, now: datetime) -> bool:
        if st.last_alert_at is None:
            return True
        return (now - st.last_alert_at) >= self._alert_cooldown

    def mark_alerted(self, st: BetState, *, now: datetime) -> None:
        st.last_alert_at = now

    def _apply_tier(self, st: BetState) -> None:
        latest = st.history[-1]
        target = tier_for_p(latest.p_hit, self._policy)

        if st.current_tier is None:
            st.current_tier = target
            return

        if target == st.current_tier:
            st._down_count = 0
            return

        # If worsening, require consecutive confirmations
        # NOTE: simple ordering by tier severity (strong->exit)
        order = {
            StatusTier.STRONG: 0,
            StatusTier.OK: 1,
            StatusTier.WATCH: 2,
            StatusTier.DANGER: 3,
            StatusTier.EXIT: 4,
        }

        is_worse = order[target] > order[st.current_tier]
        if is_worse:
            st._down_count += 1
            if st._down_count >= self._policy.consecutive_down:
                st.current_tier = target
                st._down_count = 0
            return

        # Improving: require p to exceed threshold + hysteresis
        # (placeholder: implement properly when we wire tier thresholds)
        st.current_tier = target
        st._down_count = 0

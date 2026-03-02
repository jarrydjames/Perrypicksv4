from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from .types import BetTicket, MarketSnapshot, ProbabilityEstimate, StatusTier


_TIER_EMOJI = {
    StatusTier.STRONG: "🟢",
    StatusTier.OK: "🔵",
    StatusTier.WATCH: "🟡",
    StatusTier.DANGER: "🟠",
    StatusTier.EXIT: "🔴",
}


def build_embed(*, ticket: BetTicket, snap: MarketSnapshot, est: ProbabilityEstimate) -> Dict:
    """Build a Discord embed payload (no sending)."""

    tier = est.tier
    tier_emoji = _TIER_EMOJI.get(tier, "⚪") if tier else "⚪"

    title = f"{tier_emoji} Market Likelihood (Book-Implied)"

    desc_lines = [
        f"**Ticket:** {ticket.bet_type.value} {ticket.side.value} {ticket.line:+.1f} ({ticket.odds_american:+d})",
        f"**Live:** line {snap.line_current:+.1f} | odds {snap.odds_side_a_american:+d}/{snap.odds_side_b_american:+d}",
        "",
        f"**Likelihood ticket wins:** {est.p_hit*100:.0f}%",
    ]

    if est.delta_2m is not None:
        arrow = "▲" if est.delta_2m > 0 else "▼" if est.delta_2m < 0 else "→"
        desc_lines.append(f"**Trend (2m):** {arrow} {abs(est.delta_2m)*100:.0f}%")

    if est.move_points_against_ticket is not None:
        desc_lines.append(f"**Move vs ticket:** {est.move_points_against_ticket:+.1f} pts")

    if est.notes:
        desc_lines.append("")
        desc_lines.extend([f"• {n}" for n in est.notes[:5]])

    return {
        "title": title,
        "description": "\n".join(desc_lines)[:3900],
        "color": 0x3498DB,
        "footer": {"text": f"Book: {snap.bookmaker} | Prototype"},
    }

"""
Multi-Channel Discord Router for PerryPicks

Routes predictions to different Discord channels based on confidence,
bet type, and user preferences.

Channel Types:
- MAIN: Standard halftime predictions
- HIGH_CONFIDENCE: Predictions with confidence tier A or >65% win prob
- SGP: Same Game Parlay suggestions when multiple high-confidence picks exist
- ALERTS: Critical notifications (system status, errors)

Usage:
    from src.automation.channel_router import ChannelRouter

    router = ChannelRouter(
        main_webhook="https://discord.com/api/webhooks/...",
        high_confidence_webhook="https://discord.com/api/webhooks/...",
    )
    router.route_prediction(prediction, recommendations)
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from src.automation.discord_client import DiscordClient, DiscordPostResult

logger = logging.getLogger(__name__)


class ChannelType(Enum):
    """Types of Discord channels for routing."""
    MAIN = "main"
    HIGH_CONFIDENCE = "high_confidence"
    SGP = "sgp"  # Same Game Parlays
    ALERTS = "alerts"


@dataclass
class ChannelConfig:
    """Configuration for a Discord channel."""
    webhook_url: str
    enabled: bool = True
    min_confidence: float = 0.0  # Minimum confidence to post (0.0 - 1.0)
    bet_types: List[str] = field(default_factory=lambda: ["total", "spread", "ml"])
    username: str = "PerryPicks"


@dataclass
class RoutingDecision:
    """Result of routing decision."""
    channel: ChannelType
    should_post: bool
    reason: str
    modified_content: Optional[str] = None


class ChannelRouter:
    """
    Routes predictions to appropriate Discord channels.

    Logic:
    - HIGH_CONFIDENCE: Any pick with tier A OR win prob >65%
    - SGP: Multiple picks from same game with tier B+ or better
    - MAIN: All standard predictions
    - ALERTS: System notifications only
    """

    # Confidence thresholds
    HIGH_CONFIDENCE_THRESHOLD = 0.65  # 65% win probability
    SGP_MIN_PICKS = 2  # Minimum picks for SGP suggestion
    SGP_MIN_TIER = "B+"  # Minimum tier for SGP inclusion

    def __init__(
        self,
        main_webhook: Optional[str] = None,
        high_confidence_webhook: Optional[str] = None,
        sgp_webhook: Optional[str] = None,
        alerts_webhook: Optional[str] = None,
        post_to_main_always: bool = True,
    ):
        """
        Initialize channel router.

        Args:
            main_webhook: Webhook for standard predictions
            high_confidence_webhook: Webhook for high confidence picks
            sgp_webhook: Webhook for SGP suggestions
            alerts_webhook: Webhook for system alerts
            post_to_main_always: If True, always post to main even if also posted to specialty channel
        """
        self.post_to_main_always = post_to_main_always
        self._clients: Dict[ChannelType, Optional[DiscordClient]] = {}

        # Initialize clients for each channel
        if main_webhook:
            self._clients[ChannelType.MAIN] = DiscordClient(main_webhook)
        if high_confidence_webhook:
            self._clients[ChannelType.HIGH_CONFIDENCE] = DiscordClient(high_confidence_webhook)
        if sgp_webhook:
            self._clients[ChannelType.SGP] = DiscordClient(sgp_webhook)
        if alerts_webhook:
            self._clients[ChannelType.ALERTS] = DiscordClient(alerts_webhook)

    def route_prediction(
        self,
        content: str,
        prediction: dict,
        recommendations: List[dict],
    ) -> Dict[ChannelType, DiscordPostResult]:
        """
        Route a prediction to appropriate channels.

        Args:
            content: Full message content
            prediction: Prediction dict with home_win_prob, etc.
            recommendations: List of betting recommendations

        Returns:
            Dict mapping channel types to post results
        """
        results = {}
        channels_to_post = []

        # Check for high confidence picks
        has_high_confidence = self._check_high_confidence(prediction, recommendations)
        if has_high_confidence:
            channels_to_post.append(ChannelType.HIGH_CONFIDENCE)

        # Check for SGP opportunity
        sgp_picks = self._get_sgp_picks(recommendations)
        if len(sgp_picks) >= self.SGP_MIN_PICKS:
            channels_to_post.append(ChannelType.SGP)

        # Always post to main (if configured)
        if self.post_to_main_always or not channels_to_post:
            channels_to_post.append(ChannelType.MAIN)

        # Post to each channel
        for channel in channels_to_post:
            if channel in self._clients and self._clients[channel]:
                modified_content = self._modify_for_channel(content, channel, prediction, recommendations)
                result = self._clients[channel].post_message(modified_content)
                results[channel] = result

                if result.success:
                    logger.info(f"Posted to {channel.value} channel")
                else:
                    logger.error(f"Failed to post to {channel.value}: {result.error}")

        return results

    def _check_high_confidence(self, prediction: dict, recommendations: List[dict]) -> bool:
        """Check if any pick qualifies as high confidence."""
        # Check win probability
        home_win_prob = prediction.get("home_win_prob", 0.5)
        away_win_prob = 1 - home_win_prob
        max_win_prob = max(home_win_prob, away_win_prob)

        if max_win_prob >= self.HIGH_CONFIDENCE_THRESHOLD:
            return True

        # Check recommendation tiers
        for rec in recommendations:
            tier = rec.get("confidence_tier", "B")
            if tier == "A":
                return True
            prob = rec.get("probability", 0)
            if prob >= self.HIGH_CONFIDENCE_THRESHOLD:
                return True

        return False

    def _get_sgp_picks(self, recommendations: List[dict]) -> List[dict]:
        """Get picks that qualify for SGP inclusion."""
        tier_order = {"A": 0, "B+": 1, "B": 2, "C": 3}

        sgp_picks = []
        for rec in recommendations:
            tier = rec.get("confidence_tier", "B")
            # Only include if tier is good enough
            if tier_order.get(tier, 3) <= tier_order.get(self.SGP_MIN_TIER, 1):
                sgp_picks.append(rec)

        return sgp_picks

    def _modify_for_channel(
        self,
        content: str,
        channel: ChannelType,
        prediction: dict,
        recommendations: List[dict],
    ) -> str:
        """Modify content for specific channel."""
        if channel == ChannelType.MAIN:
            return content

        if channel == ChannelType.HIGH_CONFIDENCE:
            # Generate simplified high confidence post
            return self._format_high_confidence(prediction, recommendations)

        if channel == ChannelType.SGP:
            # Generate SGP suggestion
            sgp_picks = self._get_sgp_picks(recommendations)
            if len(sgp_picks) >= 2:
                header = "**SAME GAME PARLAY OPPORTUNITY**\n\n"
                sgp_section = "\n\n---\n\n**SGP LEGS:**\n"
                for pick in sgp_picks:
                    tier = pick.get("confidence_tier", "B")
                    pick_text = pick.get("pick", "")
                    prob = pick.get("probability", 0)
                    sgp_section += f"- {pick_text} ({tier}, {prob:.0%})\n"
                return header + content + sgp_section

        return content

    def _format_high_confidence(self, prediction: dict, recommendations: List[dict]) -> str:
        """Generate a simplified high confidence alert focused on speed."""
        lines = []

        # Get top recommendation
        if not recommendations:
            return ""

        top_rec = max(recommendations, key=lambda r: r.get("probability", 0))
        prob = top_rec.get("probability", 0)
        pick = top_rec.get("pick", "")
        bet_type = top_rec.get("bet_type", "")
        edge = top_rec.get("edge", 0)
        tier = top_rec.get("confidence_tier", "B")

        # Game info
        away_team = prediction.get("away_team", "AWAY")
        home_team = prediction.get("home_team", "HOME")
        h1_away = prediction.get("h1_away", 0)
        h1_home = prediction.get("h1_home", 0)
        pred_total = prediction.get("pred_total", 0)
        pred_margin = prediction.get("pred_margin", 0)
        home_win_prob = prediction.get("home_win_prob", 0.5)

        # Calculate derived values
        pred_home_score = (pred_total + pred_margin) / 2
        pred_away_score = (pred_total - pred_margin) / 2

        # Get efficiency stats if available
        home_efg = prediction.get("home_efg", 0)
        away_efg = prediction.get("away_efg", 0)
        home_tor = prediction.get("home_tor", 0)
        away_tor = prediction.get("away_tor", 0)

        # Determine winner
        if pred_margin > 0:
            winner_team = home_team
            winner_prob = home_win_prob
        else:
            winner_team = away_team
            winner_prob = 1 - home_win_prob

        # Format edge description based on bet type
        if bet_type == "ml":
            edge_desc = f"{abs(edge):.0%} edge over implied odds"
            edge_detail = f"Model win probability ({prob:.0%}) significantly exceeds breakeven"
        else:
            edge_desc = f"{abs(edge):.1f} points better than the line"
            edge_detail = f"Model projects {pred_total:.0f} total points"

        # Build the post
        lines.append("🔥 **HIGH CONFIDENCE ALERT**")
        lines.append("")
        lines.append(f"**{away_team} @ {home_team}**")
        lines.append(f"Halftime: {away_team} {h1_away} - {h1_home} {home_team}")
        lines.append("")
        lines.append(f"**RECOMMENDATION: {pick.upper()}** ({tier})")
        lines.append(f"Hit Probability: **{prob:.1%}**")
        lines.append("")
        lines.append("**Why this bet:**")

        # Add edge analysis
        lines.append(f"• {edge_desc}")

        # Add model projection context
        if bet_type == "ml":
            favored = home_team if pred_margin > 0 else away_team
            lines.append(f"• Model projects {favored} wins by {abs(pred_margin):.1f} pts ({winner_prob:.0%} confidence)")
        elif bet_type == "total":
            lines.append(f"• Model projects {pred_total:.0f} total points")
        elif bet_type == "spread":
            favored = home_team if pred_margin > 0 else away_team
            lines.append(f"• Model projects {favored} wins by {abs(pred_margin):.1f}")

        # Add efficiency context if available
        if home_efg > 0 or away_efg > 0:
            lines.append(f"• 1H Efficiency: {home_team} eFG {home_efg:.0%} | {away_team} eFG {away_efg:.0%}")

        lines.append("")
        lines.append(f"_PerryPicks REPTAR Model_")

        return "\n".join(lines)

    def post_alert(self, message: str, level: str = "info") -> Optional[DiscordPostResult]:
        """
        Post system alert to alerts channel.

        Args:
            message: Alert message
            level: Alert level (info, warning, error)

        Returns:
            DiscordPostResult or None
        """
        if ChannelType.ALERTS not in self._clients:
            logger.warning("No alerts channel configured")
            return None

        # Add level emoji
        level_emoji = {
            "info": "INFO",
            "warning": "WARNING",
            "error": "ERROR",
        }

        formatted = f"[{level_emoji.get(level, 'INFO')}] {message}"
        return self._clients[ChannelType.ALERTS].post_message(formatted)

    def close(self) -> None:
        """Close all Discord clients."""
        for client in self._clients.values():
            if client:
                try:
                    client.close()
                except Exception:
                    pass


def create_router_from_env() -> ChannelRouter:
    """
    Create channel router from environment variables.

    Environment variables:
        DISCORD_WEBHOOK_URL: Main channel webhook
        DISCORD_HIGH_CONFIDENCE_WEBHOOK: High confidence channel webhook
        DISCORD_SGP_WEBHOOK: SGP channel webhook
        DISCORD_ALERTS_WEBHOOK: Alerts channel webhook
    """
    import os

    return ChannelRouter(
        main_webhook=os.environ.get("DISCORD_WEBHOOK_URL"),
        high_confidence_webhook=os.environ.get("DISCORD_HIGH_CONFIDENCE_WEBHOOK"),
        sgp_webhook=os.environ.get("DISCORD_SGP_WEBHOOK"),
        alerts_webhook=os.environ.get("DISCORD_ALERTS_WEBHOOK"),
    )


__all__ = ["ChannelRouter", "ChannelType", "ChannelConfig", "RoutingDecision", "create_router_from_env"]

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
    REPORT_CARD = "report_card"  # Daily accuracy and ROI report
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
    # NOTE: This is effectively your "priority bucket" threshold.
    HIGH_CONFIDENCE_THRESHOLD = 0.72  # Default: 72% (can be overridden via env)
    SGP_MIN_PICKS = 2  # Minimum picks for SGP suggestion
    SGP_MIN_TIER = "B+"  # Minimum tier for SGP inclusion

    def __init__(
        self,
        main_webhook: Optional[str] = None,
        high_confidence_webhook: Optional[str] = None,
        sgp_webhook: Optional[str] = None,
        report_card_webhook: Optional[str] = None,
        alerts_webhook: Optional[str] = None,
        post_to_main_always: bool = True,
        high_confidence_threshold: Optional[float] = None,
    ):
        """
        Initialize channel router.

        Args:
            main_webhook: Webhook for standard predictions
            high_confidence_webhook: Webhook for high confidence picks
            sgp_webhook: Webhook for SGP suggestions
            report_card_webhook: Webhook for daily report cards
            alerts_webhook: Webhook for system alerts
            post_to_main_always: If True, always post to main even if also posted to specialty channel
        """
        import os

        self.post_to_main_always = post_to_main_always
        self.high_confidence_threshold = (
            float(os.environ.get("PRIORITY_PROB_THRESHOLD", "0.72"))
            if high_confidence_threshold is None
            else float(high_confidence_threshold)
        )
        self._clients: Dict[ChannelType, Optional[DiscordClient]] = {}

        # Initialize clients for each channel
        if main_webhook:
            self._clients[ChannelType.MAIN] = DiscordClient(main_webhook)
        if high_confidence_webhook:
            self._clients[ChannelType.HIGH_CONFIDENCE] = DiscordClient(high_confidence_webhook)
        if sgp_webhook:
            self._clients[ChannelType.SGP] = DiscordClient(sgp_webhook)
        if report_card_webhook:
            self._clients[ChannelType.REPORT_CARD] = DiscordClient(report_card_webhook)
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

        # Get team names for correlation filtering
        home_team = prediction.get("home_team", "HOME")
        away_team = prediction.get("away_team", "AWAY")

        # Check for high confidence picks
        has_high_confidence = self._check_high_confidence(prediction, recommendations)
        if has_high_confidence:
            channels_to_post.append(ChannelType.HIGH_CONFIDENCE)

        # Check for SGP opportunity (with correlation filtering)
        sgp_picks = self._get_sgp_picks(recommendations, home_team, away_team)
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

        if max_win_prob >= self.high_confidence_threshold:
            return True

        # Check recommendation tiers
        for rec in recommendations:
            tier = rec.get("confidence_tier", "B")
            if tier == "A":
                return True
            prob = rec.get("probability", 0)
            if prob >= self.high_confidence_threshold:
                return True

        return False

    def _get_sgp_picks(self, recommendations: List[dict], home_team: str = "HOME", away_team: str = "AWAY") -> List[dict]:
        """Get picks that qualify for SGP inclusion.

        Correlation / related-market rules (SGP legs must be reasonably independent):
        - Never include BOTH ML and spread legs for the same game (related markets).
        - Never include game total together with BOTH team totals (related markets).
          (If game total is selected, allow at most ONE team total.)

        Legacy rule retained:
        - If both ML and spread exist for the same team, keep the one with greater edge.
        """
        tier_order = {"A+": 0, "A": 1, "B+": 2, "B": 3, "C": 4}

        # First, filter by tier
        qualified = []
        for rec in recommendations:
            tier = rec.get("confidence_tier", "B")
            if tier_order.get(tier, 4) <= tier_order.get(self.SGP_MIN_TIER, 2):
                qualified.append(rec)

        # Picks are: total (game), spread (team), ml (team), team_total (team)
        def get_team_for_pick(rec: dict) -> Optional[str]:
            """Extract which team a pick is for (None if independent like game total)."""
            bet_type = rec.get("bet_type", "").lower()
            pick_text = rec.get("pick", "")

            if bet_type == "total":
                return None  # Game totals are independent
            elif bet_type == "ml":
                # ML picks are like "BOS ML" or "HOME ML"
                if home_team in pick_text.upper() or "HOME" in pick_text.upper():
                    return home_team
                elif away_team in pick_text.upper() or "AWAY" in pick_text.upper():
                    return away_team
                # Fallback: check if pick starts with team name
                for team in [home_team, away_team]:
                    if pick_text.upper().startswith(team.upper()):
                        return team
            elif bet_type == "spread":
                # Spread picks are like "BOS -3.5" or "LAL +2.5"
                for team in [home_team, away_team]:
                    if pick_text.upper().startswith(team.upper()):
                        return team
            elif bet_type == "team_total":
                # Team total picks are like "BOS OVER 115.5"
                for team in [home_team, away_team]:
                    if pick_text.upper().startswith(team.upper()):
                        return team
            return None

        # Group by team
        by_team: Dict[Optional[str], List[dict]] = {}
        independent_picks = []

        for rec in qualified:
            team = get_team_for_pick(rec)
            if team is None:
                # Independent picks (game totals) go straight to final
                independent_picks.append(rec)
            else:
                if team not in by_team:
                    by_team[team] = []
                by_team[team].append(rec)

        # For each team, resolve ML + spread conflicts (keep highest edge)
        final_picks = list(independent_picks)

        for team, team_picks in by_team.items():
            # Separate ML and spread picks
            ml_picks = [p for p in team_picks if p.get("bet_type", "").lower() == "ml"]
            spread_picks = [p for p in team_picks if p.get("bet_type", "").lower() == "spread"]
            other_picks = [p for p in team_picks if p.get("bet_type", "").lower() not in ("ml", "spread")]

            # Add non-correlated picks directly
            final_picks.extend(other_picks)

            # If both ML and spread exist for same team, pick best by edge
            if ml_picks and spread_picks:
                best_ml = max(ml_picks, key=lambda p: abs(p.get("edge", 0)))
                best_spread = max(spread_picks, key=lambda p: abs(p.get("edge", 0)))

                # Compare edges - normalize ML edge (% to pts equivalent)
                ml_edge = abs(best_ml.get("edge", 0))
                spread_edge = abs(best_spread.get("edge", 0))

                # ML edge is a percentage, spread edge is points
                # Use a rough conversion: 5% edge ≈ 1 pt edge for comparison
                ml_edge_normalized = ml_edge * 20  # 10% = 2 pts equivalent

                if ml_edge_normalized >= spread_edge:
                    final_picks.append(best_ml)
                else:
                    final_picks.append(best_spread)
            else:
                # No conflict, add all
                final_picks.extend(ml_picks)
                final_picks.extend(spread_picks)

        # ------------------------------------------------------------------
        # Apply game-level related-market constraints
        # 1) No ML + spread in same SGP (even across different teams)
        has_ml = any(p.get("bet_type", "").lower() == "ml" for p in final_picks)
        has_spread = any(p.get("bet_type", "").lower() == "spread" for p in final_picks)
        if has_ml and has_spread:
            # Drop the lower-probability group entirely
            ml_picks_all = [p for p in final_picks if p.get("bet_type", "").lower() == "ml"]
            spread_picks_all = [p for p in final_picks if p.get("bet_type", "").lower() == "spread"]

            ml_best_prob = max((p.get("probability", 0) for p in ml_picks_all), default=0)
            spread_best_prob = max((p.get("probability", 0) for p in spread_picks_all), default=0)

            drop_type = "spread" if ml_best_prob >= spread_best_prob else "ml"
            final_picks = [p for p in final_picks if p.get("bet_type", "").lower() != drop_type]

        # 2) Totals vs team totals: don't allow game total together with BOTH team totals.
        totals = [p for p in final_picks if p.get("bet_type", "").lower() == "total"]
        team_totals = [p for p in final_picks if p.get("bet_type", "").lower() == "team_total"]
        if totals and len(team_totals) >= 2:
            # Keep the top team_total by probability; drop the other team_total(s)
            keep_tt = max(team_totals, key=lambda p: p.get("probability", 0))
            final_picks = [
                p
                for p in final_picks
                if (p.get("bet_type", "").lower() != "team_total") or (p is keep_tt)
            ]

        # Sort by probability (descending) for display
        final_picks.sort(key=lambda p: p.get("probability", 0), reverse=True)

        return final_picks

    def _calculate_combined_probability(self, picks: List[dict]) -> float:
        """
        Calculate combined probability for parlay legs (independent assumption).

        Returns probability as decimal (e.g., 0.39 for 39%).
        """
        if not picks:
            return 0.0

        combined = 1.0
        for pick in picks:
            prob = pick.get("probability", 0.5)
            combined *= prob

        return combined

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
            # Generate simplified SGP post
            home_team = prediction.get("home_team", "HOME")
            away_team = prediction.get("away_team", "AWAY")
            sgp_picks = self._get_sgp_picks(recommendations, home_team, away_team)
            if len(sgp_picks) >= self.SGP_MIN_PICKS:
                return self._format_sgp(prediction, sgp_picks)

        return content

    def _format_sgp(self, prediction: dict, sgp_picks: List[dict]) -> str:
        """Generate a simplified SGP post with combined probability."""
        lines = []

        # Game info
        away_team = prediction.get("away_team", "AWAY")
        home_team = prediction.get("home_team", "HOME")
        h1_away = prediction.get("h1_away")
        h1_home = prediction.get("h1_home")

        # Header
        lines.append("💰 **SAME GAME PARLAY**")
        lines.append("")
        lines.append(f"**{away_team} @ {home_team}**")

        if prediction.get("h1_away") is not None and prediction.get("h1_home") is not None:
            lines.append(f"Halftime: {away_team} {h1_away} - {h1_home} {home_team}")
        else:
            tip = prediction.get("game_datetime")
            if tip:
                lines.append(f"Tip: {tip}")
        lines.append("")

        # Parlay Legs - simple, focused format
        lines.append("**Parlay Legs:**")
        for i, pick in enumerate(sgp_picks[:4], 1):  # Max 4 legs
            emoji = "🔥" if i == 1 else ("✅" if i == 2 else "💰")
            pick_text = pick.get("pick", "")
            prob = pick.get("probability", 0)
            edge = pick.get("edge", 0)
            bet_type = pick.get("bet_type", "")

            # Format edge based on bet type
            if bet_type == "ml":
                edge_str = f"{abs(edge):.0%} edge"
            else:
                edge_str = f"{abs(edge):.1f} pt edge"

            lines.append(f"{emoji} {pick_text} — {prob:.0%} | {edge_str}")

        # Combined probability
        combined_prob = self._calculate_combined_probability(sgp_picks)
        lines.append("")
        lines.append(f"📊 **Combined Probability: ~{combined_prob:.0%}**")
        lines.append("")
        model = prediction.get("model_name", "REPTAR")
        lines.append(f"_PerryPicks {model} Model_")

        return "\n".join(lines)

    def _format_high_confidence(self, prediction: dict, recommendations: List[dict]) -> str:
        """Generate a simplified high confidence alert with Perry's Take."""
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
        h1_away = prediction.get("h1_away")
        h1_home = prediction.get("h1_home")
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

        # Build the post
        lines.append("🔥 **HIGH CONFIDENCE ALERT**")
        lines.append("")
        lines.append(f"**{away_team} @ {home_team}**")

        if prediction.get("h1_away") is not None and prediction.get("h1_home") is not None:
            lines.append(f"Halftime: {away_team} {h1_away} - {h1_home} {home_team}")
        else:
            tip = prediction.get("game_datetime")
            if tip:
                lines.append(f"Tip: {tip}")
        lines.append("")
        lines.append(f"**RECOMMENDATION: {pick.upper()}** ({tier})")
        lines.append(f"Hit Probability: **{prob:.1%}**")
        lines.append("")

        # Perry's Take - concise, statistically backed insight
        lines.append("**Perry's Take:**")

        # Build the insight
        insights = []

        # Edge statement
        if bet_type == "ml":
            if abs(edge) >= 0.10:
                insights.append(f"Strong {abs(edge):.0%} edge on {pick} ML")
            else:
                insights.append(f"{abs(edge):.0%} edge on {pick} ML")
        elif bet_type == "total":
            if abs(edge) >= 3:
                insights.append(f"Solid {abs(edge):.1f} pt edge on {pick}")
            else:
                insights.append(f"{abs(edge):.1f} pt edge on {pick}")
        elif bet_type == "spread":
            if abs(edge) >= 2:
                insights.append(f"Strong {abs(edge):.1f} pt edge on {pick}")
            else:
                insights.append(f"{abs(edge):.1f} pt edge on {pick}")

        # Efficiency insights
        if home_efg > 0 and away_efg > 0:
            if home_efg >= 0.60:
                insights.append(f"{home_team}'s eFG ({home_efg:.0%}) is elite")
            elif home_efg >= 0.55 and home_efg > away_efg + 0.05:
                insights.append(f"{home_team} shooting well ({home_efg:.0%} eFG)")

            if away_efg >= 0.60:
                insights.append(f"{away_team}'s eFG ({away_efg:.0%}) is elite")
            elif away_efg >= 0.55 and away_efg > home_efg + 0.05:
                insights.append(f"{away_team} shooting well ({away_efg:.0%} eFG)")

        # Turnover insights (concerning if high)
        if home_tor > 0.15:
            insights.append(f"{home_team}'s TOR ({home_tor:.0%}) is concerning")
        if away_tor > 0.15:
            insights.append(f"{away_team}'s TOR ({away_tor:.0%}) is concerning")

        # Format the insight line
        if insights:
            lines.append(" ".join(insights[:3]))  # Max 3 insights for brevity

        lines.append("")
        model = prediction.get("model_name", "REPTAR")
        lines.append(f"_PerryPicks {model} Model_")

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

    def post_report_card(self, content: str) -> Optional[DiscordPostResult]:
        """
        Post daily report card to report card channel.

        Args:
            content: Report card content

        Returns:
            DiscordPostResult or None
        """
        if ChannelType.REPORT_CARD not in self._clients:
            logger.warning("No report card channel configured")
            return None

        return self._clients[ChannelType.REPORT_CARD].post_message(content)

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
        DISCORD_REPORT_CARD_WEBHOOK: Report card channel webhook
        DISCORD_ALERTS_WEBHOOK: Alerts channel webhook
    """
    import os

    return ChannelRouter(
        main_webhook=os.environ.get("DISCORD_WEBHOOK_URL"),
        high_confidence_webhook=os.environ.get("DISCORD_HIGH_CONFIDENCE_WEBHOOK"),
        sgp_webhook=os.environ.get("DISCORD_SGP_WEBHOOK"),
        report_card_webhook=os.environ.get("DISCORD_REPORT_CARD_WEBHOOK"),
        alerts_webhook=os.environ.get("DISCORD_ALERTS_WEBHOOK"),
    )


__all__ = ["ChannelRouter", "ChannelType", "ChannelConfig", "RoutingDecision", "create_router_from_env"]

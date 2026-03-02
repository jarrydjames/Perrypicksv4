"""
Post Generation for PerryPicks

Formats predictions into platform-optimized posts for Discord.
Uses v3 templates with detailed bet formatting and summaries.

Usage:
    from src.automation.post_generator import PostGenerator

    generator = PostGenerator()
    post = generator.generate_halftime_post(prediction, game_state, recommendations, odds)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from src.automation.game_state import GameState
from src.automation.triggers import TriggerType

logger = logging.getLogger(__name__)


@dataclass
class BettingRecommendation:
    """Represents a betting recommendation."""

    bet_type: str  # "total", "spread", "ml", "team_total"
    pick: str  # "OVER", "UNDER", or team name for spread/ML/team_total
    line: Optional[float] = None
    odds: Optional[int] = None
    edge: float = 0.0
    probability: float = 0.0
    confidence_tier: str = "B"  # A+, A, B+, B
    model_prediction: Optional[float] = None
    edge_unit: str = "pts"
    team_name: Optional[str] = None  # Team name for display
    is_recommended: bool = True  # True if passes thresholds, False if passed on

    @property
    def display_pick(self) -> str:
        """Get display-friendly pick name."""
        if self.team_name:
            return self.team_name
        return self.pick


@dataclass
class GeneratedPost:
    """A generated post ready for publishing."""

    content: str
    platform: str
    trigger_type: TriggerType
    game_id: str
    recommendations: List[BettingRecommendation]
    passed_bets: List[BettingRecommendation] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def character_count(self) -> int:
        """Get character count for the post."""
        return len(self.content)


class PostGenerator:
    """
    Generates platform-optimized posts from predictions.

    Uses v3 templates with detailed bet formatting including:
    - Edge and hit probability for each bet
    - Summary statistics (avg hit prob, tier counts, edge by type)
    - Confidence tier display
    - Pass recommendations showing evaluated bets
    """

    # Discord character limit
    DISCORD_MAX_CHARS = 2000

    def __init__(self, include_betting: bool = True):
        self.include_betting = include_betting

    def generate_halftime_post(
        self,
        prediction: dict,
        game_state: GameState,
        recommendations: Optional[List[BettingRecommendation]] = None,
        passed_bets: Optional[List[BettingRecommendation]] = None,
        odds_available: bool = True,
    ) -> GeneratedPost:
        """Generate a halftime prediction post with v3 template."""
        home_team = game_state.home_tricode or prediction.get("home_name", "Home")
        away_team = game_state.away_tricode or prediction.get("away_name", "Away")
        h1_home = game_state.home_score
        h1_away = game_state.away_score

        pred_total = prediction.get("pred_final_total", prediction.get("total", 0))
        pred_margin = prediction.get("pred_final_margin", prediction.get("margin", 0))
        pred_home = (pred_total + pred_margin) / 2
        pred_away = (pred_total - pred_margin) / 2
        home_win_prob = prediction.get("home_win_prob", 0.5)

        winner = home_team if pred_margin > 0 else away_team

        # Build post using v3 template format
        lines = []
        # VISUAL SEPARATOR - makes posts clearly distinct
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("")
        lines.append("🔥 **HALFTIME UPDATE**")
        lines.append("")
        lines.append(f"**{away_team} @ {home_team}**")
        lines.append("")
        lines.append(f"Halftime: {away_team} {h1_away} - {h1_home} {home_team}")
        lines.append("")
        lines.append(f"Projected Final: {away_team} {pred_away:.1f} - {pred_home:.1f} {home_team}")
        lines.append("")
        lines.append(f"Winner: **{winner}** | Margin: {pred_margin:+.1f} | Total: {pred_total:.1f}")
        winner_prob = home_win_prob if pred_margin > 0 else (1 - home_win_prob)
        lines.append(f"Win Probability: {winner_prob:.1%} {winner}")
        lines.append("")

        # Add team totals projection
        lines.append(f"Team Totals: {away_team} {pred_away:.1f} | {home_team} {pred_home:.1f}")
        lines.append("")

        # Add betting section
        if self.include_betting:
            bet_lines = self._format_bets_section(
                recommendations or [],
                passed_bets or [],
                home_team,
                away_team,
                prediction,
                odds_available,
            )
            lines.extend(bet_lines)

        # Footer with clear end marker
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"*PerryPicks REPTAR | {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC*")

        content = "\n".join(lines)

        return GeneratedPost(
            content=content[:self.DISCORD_MAX_CHARS],
            platform="discord",
            trigger_type=TriggerType.HALFTIME,
            game_id=game_state.game_id,
            recommendations=recommendations or [],
            passed_bets=passed_bets or [],
            created_at=datetime.utcnow(),
        )

    def generate_pregame_post(
        self,
        prediction: dict,
        home_team: str,
        away_team: str,
        game_time: str | None = None,
        recommendations: Optional[List[BettingRecommendation]] = None,
        passed_bets: Optional[List[BettingRecommendation]] = None,
        odds_available: bool = True,
    ) -> GeneratedPost:
        """Generate a pregame prediction post (MAXIMUS)."""

        pred_total = prediction.get("total_mean", prediction.get("pred_total", prediction.get("pred_final_total", 0)))
        pred_margin = prediction.get("margin_mean", prediction.get("pred_margin", prediction.get("pred_final_margin", 0)))
        pred_home = (pred_total + pred_margin) / 2
        pred_away = (pred_total - pred_margin) / 2
        home_win_prob = prediction.get("home_win_prob", 0.5)

        winner = home_team if pred_margin > 0 else away_team
        winner_prob = home_win_prob if pred_margin > 0 else (1 - home_win_prob)

        lines = []
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("")
        lines.append("🧠 **PREGAME**")
        lines.append("")
        lines.append(f"**{away_team} @ {home_team}**")
        if game_time:
            lines.append(f"Tip-off: {game_time}")
        lines.append("")
        lines.append(f"Projected Final: {away_team} {pred_away:.1f} - {pred_home:.1f} {home_team}")
        lines.append("")
        lines.append(f"Winner: **{winner}** | Margin: {pred_margin:+.1f} | Total: {pred_total:.1f}")
        lines.append(f"Win Probability: {winner_prob:.1%} {winner}")
        lines.append("")
        lines.append(f"Team Totals: {away_team} {pred_away:.1f} | {home_team} {pred_home:.1f}")
        lines.append("")

        if self.include_betting:
            bet_lines = self._format_bets_section(
                recommendations or [],
                passed_bets or [],
                home_team,
                away_team,
                prediction,
                odds_available,
            )
            lines.extend(bet_lines)

        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        content = "\n".join(lines)

        return GeneratedPost(
            content=content[: self.DISCORD_MAX_CHARS],
            platform="discord",
            trigger_type=TriggerType.PREGAME,
            game_id=str(prediction.get("game_id", "")),
            recommendations=recommendations or [],
            passed_bets=passed_bets or [],
            created_at=datetime.utcnow(),
        )

    def generate_q3_post(
        self,
        prediction: dict,
        game_state: GameState,
        recommendations: Optional[List[BettingRecommendation]] = None,
        passed_bets: Optional[List[BettingRecommendation]] = None,
    ) -> GeneratedPost:
        """Generate a Q3 prediction post with v3 template."""
        home_team = game_state.home_tricode or prediction.get("home_name", "Home")
        away_team = game_state.away_tricode or prediction.get("away_name", "Away")
        q3_home = game_state.home_score
        q3_away = game_state.away_score

        pred_total = prediction.get("pred_final_total", prediction.get("total", 0))
        pred_margin = prediction.get("pred_final_margin", prediction.get("margin", 0))
        pred_home = (pred_total + pred_margin) / 2
        pred_away = (pred_total - pred_margin) / 2

        winner = home_team if pred_margin > 0 else away_team

        lines = []
        # VISUAL SEPARATOR - makes posts clearly distinct
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("")
        lines.append("⚡ **Q3 UPDATE (5 Min Left)**")
        lines.append("")
        lines.append(f"**{away_team} @ {home_team}**")
        lines.append("")
        lines.append(f"Current: {away_team} {q3_away} - {q3_home} {home_team}")
        lines.append("")
        lines.append(f"Projected Final: {away_team} {pred_away:.1f} - {pred_home:.1f} {home_team}")
        lines.append("")
        lines.append(f"Winner: **{winner}** | Margin: {pred_margin:+.1f} | Total: {pred_total:.1f}")
        lines.append("")

        # Add team totals projection
        lines.append(f"Team Totals: {away_team} {pred_away:.1f} | {home_team} {pred_home:.1f}")
        lines.append("")

        # Add betting section
        if self.include_betting:
            bet_lines = self._format_bets_section(
                recommendations or [],
                passed_bets or [],
                home_team,
                away_team,
                prediction,
                odds_available,
            )
            lines.extend(bet_lines)

        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"*PerryPicks REPTAR | {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC*")

        content = "\n".join(lines)

        return GeneratedPost(
            content=content[:self.DISCORD_MAX_CHARS],
            platform="discord",
            trigger_type=TriggerType.Q3_5MIN,
            game_id=game_state.game_id,
            recommendations=recommendations or [],
            passed_bets=passed_bets or [],
            created_at=datetime.utcnow(),
        )

    def _format_bets_section(
        self,
        bets: List[BettingRecommendation],
        passed_bets: List[BettingRecommendation],
        home_team: str,
        away_team: str,
        prediction: Optional[dict] = None,
        odds_available: bool = True,
    ) -> List[str]:
        """Format best bets section with v3 styling and Perry's Take."""
        lines = []

        if not bets:
            if not odds_available:
                lines.append("⚠️ **ERROR: Unable to fetch live odds from DraftKings**")
                lines.append("")
                lines.append("No betting recommendations available due to odds fetch error.")
                lines.append("")
                lines.append("Prediction is still valid - you may want to check odds manually.")
            else:
                lines.append("🎯 No bets passed edge + hit-probability thresholds at this time.")
        else:
            lines.append("🎯 **Best Bets** (sorted by edge, then hit probability)")
            lines.append("")

            for i, bet in enumerate(bets, 1):
                emoji = "🔥" if i == 1 else ("✅" if i == 2 else "💰")

                # Format side based on bet type
                side = self._format_bet_side(bet, home_team, away_team)

                # Format edge
                if bet.edge_unit == "%":
                    edge_text = f"{bet.edge*100:+.1f}%"
                else:
                    edge_text = f"{bet.edge:+.2f} pts"

                # Format odds
                odds_str = f"@ {bet.odds}" if bet.odds else ""

                lines.append(f"{emoji} **{i}. {bet.bet_type.title()}: {side}** {odds_str}")
                lines.append(f"   Edge: {edge_text} | Hit Prob: {bet.probability:.1%} | Tier: {bet.confidence_tier}")
                if bet.model_prediction is not None:
                    if bet.bet_type.lower() == "ml":
                        lines.append(f"   Model Win Prob: {bet.model_prediction:.1%}")
                    else:
                        lines.append(f"   Model Prediction: {bet.model_prediction:.1f}")
                lines.append("")

            # Summary
            avg_hit_prob = sum(b.probability for b in bets) / len(bets)
            tier_counts: Dict[str, int] = {}
            for bet in bets:
                tier = bet.confidence_tier
                tier_counts[tier] = tier_counts.get(tier, 0) + 1

            tier_summary = ", ".join(f"{tier}:{count}" for tier, count in sorted(tier_counts.items()))

            lines.append("📊 **Summary**")
            lines.append(f"   {len(bets)} bets | Avg Hit Prob: {avg_hit_prob:.1%} | Tiers: {tier_summary}")

            # Perry's Take - add conversational insight based on stats
            if prediction:
                perrys_take = self._generate_perrys_take(bets, home_team, away_team, prediction)
                if perrys_take:
                    lines.append("")
                    lines.append("**Perry's Take:**")
                    lines.append(perrys_take)

        # Add passed bets section
        if passed_bets:
            lines.append("")
            lines.append("📋 **Evaluated (Pass)**")
            lines.append("")

            # Group passed bets by type
            passed_by_type: Dict[str, List[BettingRecommendation]] = {}
            for bet in passed_bets:
                bet_type = bet.bet_type.title()
                if bet_type not in passed_by_type:
                    passed_by_type[bet_type] = []
                passed_by_type[bet_type].append(bet)

            for bet_type, type_bets in passed_by_type.items():
                sides = []
                for b in type_bets:
                    side = self._format_bet_side(b, home_team, away_team, short=True)
                    sides.append(side)
                lines.append(f"   {bet_type}: {', '.join(sides)}")

        return lines

    def _format_bet_side(
        self,
        bet: BettingRecommendation,
        home_team: str,
        away_team: str,
        short: bool = False
    ) -> str:
        """Format the side/pick for a bet."""
        # Normalize bet type (handle both "Team Total" and "team_total")
        bet_type_lower = bet.bet_type.lower().replace(" ", "_")

        if bet_type_lower == "total":
            if short:
                return f"{bet.pick} {bet.line:.1f}"
            return f"{bet.pick} {bet.line:.1f}"

        elif bet_type_lower == "team_total":
            # For team totals, bet.team_name is already set correctly in the recommendation
            # (home_team for home team totals, away_team for away team totals)
            # bet.pick is "OVER" or "UNDER", not "HOME"/"AWAY"
            if not bet.team_name:
                logger.warning(f"Team total bet missing team_name: {bet}")
                return f"Unknown {bet.pick} {bet.line:.1f}"
            if short:
                return f"{bet.team_name} {bet.pick} {bet.line:.1f}"
            return f"{bet.team_name} {bet.pick} {bet.line:.1f}"

        elif bet_type_lower == "spread":
            # For spreads, bet.pick is "HOME" or "AWAY"
            team = bet.team_name or (home_team if bet.pick == "HOME" else away_team)
            if short:
                return team
            return f"{team} {bet.line:+.1f}"

        else:  # ML
            # For moneyline, bet.pick is "HOME" or "AWAY"
            team = bet.team_name or (home_team if bet.pick == "HOME" else away_team)
            if short:
                return f"{team} ML"
            return f"{team} ML"

    def create_recommendations_from_prediction(
        self,
        prediction: dict,
        odds: Optional[dict] = None,
        home_team: str = "Home",
        away_team: str = "Away",
    ) -> tuple[List[BettingRecommendation], List[BettingRecommendation]]:
        """
        Create betting recommendations from a prediction using v3 logic.

        Returns a tuple of (recommended_bets, passed_bets).
        """
        from src.betting import (
            prob_over_under_from_mean_sd,
            prob_spread_cover_from_mean_sd,
            breakeven_prob_from_american,
        )

        recommendations = []
        passed_bets = []

        pred_total = prediction.get("pred_final_total", prediction.get("total", 0))
        pred_margin = prediction.get("pred_final_margin", prediction.get("margin", 0))
        pred_home = (pred_total + pred_margin) / 2
        pred_away = (pred_total - pred_margin) / 2
        home_win_prob = prediction.get("home_win_prob", 0.5)
        total_sd = float(prediction.get("total_sd", 10.87) or 10.87)
        margin_sd = float(prediction.get("margin_sd", 7.76) or 7.76)

        # If no odds, return empty
        if not odds:
            return recommendations, passed_bets

        # --- TOTALS ---
        total_line = odds.get("total_points")
        if total_line is not None:
            p_over = prob_over_under_from_mean_sd(float(pred_total), total_sd, float(total_line))
            p_under = 1.0 - p_over

            # Over
            edge_over = float(pred_total) - float(total_line)
            rec_over = BettingRecommendation(
                bet_type="Total",
                pick="OVER",
                line=float(total_line),
                odds=odds.get("total_over_odds"),
                edge=edge_over,
                probability=p_over,
                confidence_tier=self._confidence_tier(p_over),
                model_prediction=float(pred_total),
                edge_unit="pts",
                is_recommended=(edge_over >= 2.0 and p_over >= 0.56),
            )
            if rec_over.is_recommended:
                recommendations.append(rec_over)
            else:
                passed_bets.append(rec_over)

            # Under
            edge_under = float(total_line) - float(pred_total)
            rec_under = BettingRecommendation(
                bet_type="Total",
                pick="UNDER",
                line=float(total_line),
                odds=odds.get("total_under_odds"),
                edge=edge_under,
                probability=p_under,
                confidence_tier=self._confidence_tier(p_under),
                model_prediction=float(pred_total),
                edge_unit="pts",
                is_recommended=(edge_under >= 2.0 and p_under >= 0.56),
            )
            if rec_under.is_recommended:
                recommendations.append(rec_under)
            else:
                passed_bets.append(rec_under)

        # --- SPREADS ---
        spread_home = odds.get("spread_home")
        if spread_home is not None:
            p_home_cover = prob_spread_cover_from_mean_sd(float(pred_margin), margin_sd, float(spread_home))
            p_away_cover = 1.0 - p_home_cover

            # Home spread
            edge_home = float(pred_margin) + float(spread_home)
            rec_home_spread = BettingRecommendation(
                bet_type="Spread",
                pick="HOME",
                line=float(spread_home),
                odds=odds.get("spread_home_odds"),
                edge=edge_home,
                probability=p_home_cover,
                confidence_tier=self._confidence_tier(p_home_cover),
                model_prediction=float(pred_margin),
                edge_unit="pts",
                team_name=home_team,
                is_recommended=(edge_home >= 1.5 and p_home_cover >= 0.57),
            )
            if rec_home_spread.is_recommended:
                recommendations.append(rec_home_spread)
            else:
                passed_bets.append(rec_home_spread)

            # Away spread
            edge_away = -edge_home
            rec_away_spread = BettingRecommendation(
                bet_type="Spread",
                pick="AWAY",
                line=-float(spread_home),
                odds=odds.get("spread_away_odds"),
                edge=edge_away,
                probability=p_away_cover,
                confidence_tier=self._confidence_tier(p_away_cover),
                model_prediction=float(-pred_margin),
                edge_unit="pts",
                team_name=away_team,
                is_recommended=(edge_away >= 1.5 and p_away_cover >= 0.57),
            )
            if rec_away_spread.is_recommended:
                recommendations.append(rec_away_spread)
            else:
                passed_bets.append(rec_away_spread)

        # --- MONEYLINE ---
        ml_home = odds.get("moneyline_home")
        ml_away = odds.get("moneyline_away")
        if ml_home is not None and ml_away is not None:
            try:
                home_be = breakeven_prob_from_american(int(ml_home))
                away_be = breakeven_prob_from_american(int(ml_away))

                edge_home_ml = home_win_prob - home_be
                edge_away_ml = (1.0 - home_win_prob) - away_be

                # Home ML
                rec_home_ml = BettingRecommendation(
                    bet_type="ML",
                    pick="HOME",
                    odds=int(ml_home),
                    edge=edge_home_ml,
                    probability=home_win_prob,
                    confidence_tier=self._confidence_tier(home_win_prob),
                    model_prediction=home_win_prob,
                    edge_unit="%",
                    team_name=home_team,
                    is_recommended=(edge_home_ml >= 0.03 and home_win_prob >= 0.58),
                )
                if rec_home_ml.is_recommended:
                    recommendations.append(rec_home_ml)
                else:
                    passed_bets.append(rec_home_ml)

                # Away ML
                rec_away_ml = BettingRecommendation(
                    bet_type="ML",
                    pick="AWAY",
                    odds=int(ml_away),
                    edge=edge_away_ml,
                    probability=1.0 - home_win_prob,
                    confidence_tier=self._confidence_tier(1.0 - home_win_prob),
                    model_prediction=1.0 - home_win_prob,
                    edge_unit="%",
                    team_name=away_team,
                    is_recommended=(edge_away_ml >= 0.03 and (1.0 - home_win_prob) >= 0.58),
                )
                if rec_away_ml.is_recommended:
                    recommendations.append(rec_away_ml)
                else:
                    passed_bets.append(rec_away_ml)

            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to process moneyline odds: {e}")

        # --- TEAM TOTALS ---
        team_total_home = odds.get("team_total_home")
        team_total_away = odds.get("team_total_away")
        
        # Derive team totals from game total and spread if not provided
        if team_total_home is None and team_total_away is None:
            total_points = odds.get("total_points")
            spread_home = odds.get("spread_home")
            
            if total_points is not None and spread_home is not None:
                # Formula (spread_home is home line, e.g., -3.5 means home is favored):
                # Spread represents the expected margin: Home - Away = spread
                # If spread is negative (home favored), home scores MORE, away scores LESS
                # Home Team Total = (Game Total - Spread) / 2
                # Away Team Total = (Game Total + Spread) / 2
                # Example: Total 240.5, Spread -6.5 (home favored)
                #   Home: (240.5 - (-6.5)) / 2 = 123.5 (home scores more!)
                #   Away: (240.5 + (-6.5)) / 2 = 117.0 (away scores less!)
                # Verify: 123.5 + 117.0 = 240.5 ✓
                #           123.5 - 117.0 = 6.5 = -(-6.5) ✓
                team_total_home = (total_points - spread_home) / 2
                team_total_away = (total_points + spread_home) / 2
                logger.info(f"Derived team totals from total={total_points}, spread={spread_home}")
                logger.info(f"  Home team total: {team_total_home:.1f}")
                logger.info(f"  Away team total: {team_total_away:.1f}")

        # Home team total
        if team_total_home is not None:
            p_home_over = prob_over_under_from_mean_sd(float(pred_home), total_sd * 0.7, float(team_total_home))
            p_home_under = 1.0 - p_home_over

            # Home Over
            edge_home_over = float(pred_home) - float(team_total_home)
            rec_home_over = BettingRecommendation(
                bet_type="Team Total",
                pick="OVER",
                line=float(team_total_home),
                odds=odds.get("team_total_home_over_odds"),
                edge=edge_home_over,
                probability=p_home_over,
                confidence_tier=self._confidence_tier(p_home_over),
                model_prediction=float(pred_home),
                edge_unit="pts",
                team_name=home_team,
                is_recommended=(edge_home_over >= 1.5 and p_home_over >= 0.56),
            )
            if rec_home_over.is_recommended:
                recommendations.append(rec_home_over)
            else:
                passed_bets.append(rec_home_over)

            # Home Under
            edge_home_under = float(team_total_home) - float(pred_home)
            rec_home_under = BettingRecommendation(
                bet_type="Team Total",
                pick="UNDER",
                line=float(team_total_home),
                odds=odds.get("team_total_home_under_odds"),
                edge=edge_home_under,
                probability=p_home_under,
                confidence_tier=self._confidence_tier(p_home_under),
                model_prediction=float(pred_home),
                edge_unit="pts",
                team_name=home_team,
                is_recommended=(edge_home_under >= 1.5 and p_home_under >= 0.56),
            )
            if rec_home_under.is_recommended:
                recommendations.append(rec_home_under)
            else:
                passed_bets.append(rec_home_under)

        # Away team total
        if team_total_away is not None:
            p_away_over = prob_over_under_from_mean_sd(float(pred_away), total_sd * 0.7, float(team_total_away))
            p_away_under = 1.0 - p_away_over

            # Away Over
            edge_away_over = float(pred_away) - float(team_total_away)
            rec_away_over = BettingRecommendation(
                bet_type="Team Total",
                pick="OVER",
                line=float(team_total_away),
                odds=odds.get("team_total_away_over_odds"),
                edge=edge_away_over,
                probability=p_away_over,
                confidence_tier=self._confidence_tier(p_away_over),
                model_prediction=float(pred_away),
                edge_unit="pts",
                team_name=away_team,
                is_recommended=(edge_away_over >= 1.5 and p_away_over >= 0.56),
            )
            if rec_away_over.is_recommended:
                recommendations.append(rec_away_over)
            else:
                passed_bets.append(rec_away_over)

            # Away Under
            edge_away_under = float(team_total_away) - float(pred_away)
            rec_away_under = BettingRecommendation(
                bet_type="Team Total",
                pick="UNDER",
                line=float(team_total_away),
                odds=odds.get("team_total_away_under_odds"),
                edge=edge_away_under,
                probability=p_away_under,
                confidence_tier=self._confidence_tier(p_away_under),
                model_prediction=float(pred_away),
                edge_unit="pts",
                team_name=away_team,
                is_recommended=(edge_away_under >= 1.5 and p_away_under >= 0.56),
            )
            if rec_away_under.is_recommended:
                recommendations.append(rec_away_under)
            else:
                passed_bets.append(rec_away_under)

        # Sort recommendations by edge (descending)
        recommendations.sort(key=lambda r: (r.edge, r.probability), reverse=True)

        # Sort passed bets by bet type for clean display
        type_order = {"Total": 0, "Spread": 1, "ML": 2, "Team Total": 3}
        passed_bets.sort(key=lambda r: (type_order.get(r.bet_type, 99), r.team_name or r.pick))

        return recommendations[:3], passed_bets

    def _confidence_tier(self, probability: float) -> str:
        """Map probability to confidence tier."""
        p = float(probability)
        if p >= 0.80:
            return "A+"
        if p >= 0.75:
            return "A"
        if p >= 0.65:
            return "B+"
        if p >= 0.56:
            return "B"
        return "No bet"

    def _generate_perrys_take(
        self,
        bets: List[BettingRecommendation],
        home_team: str,
        away_team: str,
        prediction: dict,
    ) -> str:
        """Generate conversational, statistically-backed insight for Perry's Take."""
        if not bets:
            return ""

        # Get top recommendation
        top_bet = bets[0]  # Already sorted by edge

        # Extract stats from prediction
        home_efg = prediction.get("home_efg", 0)
        away_efg = prediction.get("away_efg", 0)
        home_tor = prediction.get("home_tor", 0)
        away_tor = prediction.get("away_tor", 0)
        pred_margin = prediction.get("pred_final_margin", prediction.get("margin", 0))

        # Build insights
        insights = []

        # Determine edge direction
        if pred_margin > 0:
            favored_team = home_team
        else:
            favored_team = away_team

        # Edge statement based on top bet
        if top_bet.bet_type.lower() == "ml":
            edge_val = abs(top_bet.edge)
            if edge_val >= 0.10:
                insights.append(f"Clear edge to {favored_team}")
                insights.append(f"The {edge_val:.0%} edge on {top_bet.team_name or top_bet.pick} ML is strong")
            else:
                insights.append(f"{edge_val:.0%} edge on {top_bet.team_name or top_bet.pick} ML")
        elif top_bet.bet_type.lower() == "total":
            edge_val = abs(top_bet.edge)
            if edge_val >= 3:
                insights.append(f"Solid {edge_val:.1f} pt edge on {top_bet.pick}")
            else:
                insights.append(f"{edge_val:.1f} pt edge on {top_bet.pick}")
        elif top_bet.bet_type.lower() == "spread":
            edge_val = abs(top_bet.edge)
            if edge_val >= 2:
                insights.append(f"Strong {edge_val:.1f} pt edge on {top_bet.team_name or favored_team}")
            else:
                insights.append(f"{edge_val:.1f} pt edge on {top_bet.team_name or favored_team}")

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

        # Build recommendation with action
        rec_parts = []
        for bet in bets[:2]:  # Top 2 recommendations
            if bet.bet_type.lower() == "ml":
                rec_parts.append(f"{bet.team_name or bet.pick} ML")
            elif bet.bet_type.lower() == "spread":
                rec_parts.append(f"{bet.team_name or bet.pick} {bet.line:+.1f}")
            elif bet.bet_type.lower() == "total":
                rec_parts.append(f"{bet.pick} {bet.line:.1f}")

        # Format final take
        take = " ".join(insights[:4])  # Max 4 insights for readability
        if rec_parts:
            take += f". Take {', '.join(rec_parts)}."

        return take


__all__ = ["PostGenerator", "GeneratedPost", "BettingRecommendation"]

"""
Prediction Report Generator

Generates formatted prediction reports in two styles:
- FULL: Detailed EV analysis matching the standard format
- COMPACT: Quick one-line summary

Usage:
    from src.analysis.prediction_report import generate_report

    report = generate_report(game_id="0022500801", format="full")
    print(report)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from scipy.stats import norm

logger = logging.getLogger(__name__)

# Model performance metrics (from REPTAR training)
SIGMA_TOTAL = 16.0    # RMSE for final total prediction
SIGMA_MARGIN = 5.4    # RMSE for final margin prediction
H2_TOTAL_MAE = 7.96
H2_MARGIN_MAE = 3.85


def _safe_calculate_ev(pred_value: float, line_value: float, sigma: float, odds: int) -> dict:
    """Calculate EV with edge case handling.

    Returns dict with edge, probability, EV, and validity flag.
    """
    # Handle missing/invalid inputs
    if line_value is None or line_value == 0:
        return {
            "edge": None,
            "z_score": None,
            "probability": None,
            "ev": None,
            "valid": False,
            "reason": "No line available"
        }

    if odds is None or odds == 0:
        return {
            "edge": None,
            "z_score": None,
            "probability": None,
            "ev": None,
            "valid": False,
            "reason": "No odds available"
        }

    if sigma is None or sigma <= 0:
        sigma = 0.1  # Avoid division by zero

    # Calculate edge
    edge = pred_value - line_value

    # Calculate Z-score
    z = edge / sigma

    # Calculate probability (direction depends on edge sign)
    if edge > 0:
        probability = (1 - norm.cdf(-z)) * 100
    else:
        probability = norm.cdf(-z) * 100

    # Calculate payout multiplier
    if odds > 0:
        payout = 1 + odds / 100
    else:
        payout = 1 + 100 / abs(odds)

    # Calculate EV
    ev = (probability / 100) * payout - 1
    ev_pct = ev * 100

    return {
        "edge": edge,
        "z_score": z,
        "probability": probability,
        "ev": ev_pct,
        "payout": payout,
        "valid": True,
        "reason": None
    }


class ReportFormat(Enum):
    FULL = "full"
    COMPACT = "compact"


@dataclass
class BettingRecommendation:
    """Single betting recommendation with EV analysis."""
    bet_type: str          # "TOTAL" or "SPREAD"
    selection: str         # "OVER 220.5" or "LAC +7.5"
    line: float
    edge: float
    edge_sigma: float
    probability: float
    odds: int
    payout: float
    ev: float
    action: str            # "BET" or "PASS"
    side_desc: str         # e.g., "DEN -7.5 covers" or "UNDER hits"


@dataclass
class PredictionReport:
    """Complete prediction report for a game."""
    game_id: str
    away_team: str
    home_team: str

    # Live game data
    current_period: int
    current_away_score: int
    current_home_score: int
    halftime_away: int
    halftime_home: int

    # Model predictions
    pred_final_away: float
    pred_final_home: float
    pred_total: float
    pred_margin: float
    home_win_prob: float
    away_win_prob: float
    total_q10: float
    total_q90: float
    margin_q10: float
    margin_q90: float

    # Efficiency stats
    home_efg: float
    away_efg: float
    home_tor: float
    away_tor: float

    # Market odds
    line_total: float
    total_over_odds: int
    total_under_odds: int
    line_spread: float
    spread_home_odds: int
    spread_away_odds: int
    moneyline_home: Optional[int]
    moneyline_away: Optional[int]
    bookmaker: str

    # Recommendations
    total_rec: BettingRecommendation
    spread_rec: BettingRecommendation
    best_bet: Optional[BettingRecommendation]


def _calculate_ev(probability: float, odds: int) -> Tuple[float, float]:
    """Calculate payout and EV for given probability and odds."""
    if odds > 0:
        payout = 1 + odds / 100
    else:
        payout = 1 + 100 / abs(odds)

    ev = (probability / 100) * payout - 1
    return payout, ev * 100


def _analyze_total(pred_total: float, line_total: float,
                   over_odds: int, under_odds: int) -> BettingRecommendation:
    """Analyze total betting market with edge case handling."""

    # Handle missing odds
    if line_total is None or line_total == 0:
        return BettingRecommendation(
            bet_type="TOTAL",
            selection="N/A",
            line=0,
            edge=0,
            edge_sigma=0,
            probability=0,
            odds=0,
            payout=0,
            ev=-100,
            action="PASS",
            side_desc="No line available"
        )

    edge = pred_total - line_total
    z = edge / SIGMA_TOTAL if SIGMA_TOTAL > 0 else 0

    if edge > 0:
        selection = f"OVER {line_total}"
        side_desc = "OVER hits"
        odds = over_odds if over_odds else -110
        prob = (1 - norm.cdf(-z)) * 100
    else:
        selection = f"UNDER {line_total}"
        side_desc = "UNDER hits"
        odds = under_odds if under_odds else -110
        prob = norm.cdf(-z) * 100

    payout, ev = _calculate_ev(prob, odds)
    action = "BET" if ev > 0 else "PASS"

    return BettingRecommendation(
        bet_type="TOTAL",
        selection=selection,
        line=line_total,
        edge=edge,
        edge_sigma=abs(z),
        probability=prob,
        odds=odds,
        payout=payout,
        ev=ev,
        action=action,
        side_desc=side_desc
    )


def _analyze_spread(pred_margin: float, line_spread: float,
                    home_odds: int, away_odds: int,
                    home_team: str, away_team: str) -> BettingRecommendation:
    """Analyze spread betting market with edge case handling."""

    # Handle missing spread
    if line_spread is None:
        return BettingRecommendation(
            bet_type="SPREAD",
            selection="N/A",
            line=0,
            edge=0,
            edge_sigma=0,
            probability=0,
            odds=0,
            payout=0,
            ev=-100,
            action="PASS",
            side_desc="No spread available"
        )

    # pred_margin positive = home wins
    # line_spread from home perspective (e.g., +7.5 means home gets 7.5)

    if line_spread > 0:
        # Home getting points (e.g., LAC +7.5)
        margin_to_beat = -line_spread
        if pred_margin > margin_to_beat:
            # Home covers
            selection = f"{home_team} +{line_spread:.1f}"
            side_desc = f"{home_team} +{line_spread:.1f} covers"
            edge = pred_margin - margin_to_beat
            odds = home_odds if home_odds else -110
        else:
            # Away covers
            selection = f"{away_team} -{line_spread:.1f}"
            side_desc = f"{away_team} -{line_spread:.1f} covers"
            edge = margin_to_beat - pred_margin
            odds = away_odds if away_odds else -110
    else:
        # Home favored (e.g., DEN -7.5, so line_spread = -7.5)
        if pred_margin > line_spread:
            # Home covers
            selection = f"{home_team} {line_spread:+.1f}"
            side_desc = f"{home_team} {line_spread:+.1f} covers"
            edge = pred_margin - line_spread
            odds = home_odds if home_odds else -110
        else:
            # Away covers
            selection = f"{away_team} +{abs(line_spread):.1f}"
            side_desc = f"{away_team} +{abs(line_spread):.1f} covers"
            edge = line_spread - pred_margin
            odds = away_odds if away_odds else -110

    z = edge / SIGMA_MARGIN if SIGMA_MARGIN > 0 else 0
    prob = (1 - norm.cdf(-z)) * 100
    payout, ev = _calculate_ev(prob, odds)
    action = "BET" if ev > 0 else "PASS"

    return BettingRecommendation(
        bet_type="SPREAD",
        selection=selection,
        line=line_spread,
        edge=edge,
        edge_sigma=abs(z),
        probability=prob,
        odds=odds,
        payout=payout,
        ev=ev,
        action=action,
        side_desc=side_desc
    )


def generate_report(
    game_id: str,
    format: str = "full",
    predictor=None,
    odds_snapshot=None
) -> str:
    """
    Generate a prediction report for a game.

    Args:
        game_id: NBA game ID
        format: "full" or "compact"
        predictor: Optional pre-loaded ReptarPredictor
        odds_snapshot: Optional pre-fetched odds snapshot

    Returns:
        Formatted report string
    """
    from src.models.reptar_predictor import ReptarPredictor, get_predictor
    from src.odds.odds_api import fetch_nba_odds_snapshot
    from src.data.game_data import fetch_box, first_half_score, get_efficiency_stats_from_box

    # Load predictor if not provided
    if predictor is None:
        predictor = get_predictor()

    # Get prediction
    pred = predictor.predict_from_game_id(game_id)
    if pred is None:
        return f"ERROR: Could not generate prediction for game {game_id}"

    # Get odds if not provided
    if odds_snapshot is None:
        try:
            odds_snapshot = fetch_nba_odds_snapshot(
                home_name=pred.home_team,
                away_name=pred.away_team
            )
        except Exception as e:
            return f"ERROR: Could not fetch odds: {e}"

    # Get live game data
    try:
        box = fetch_box(game_id)
        h1_home, h1_away = first_half_score(box)
        eff = get_efficiency_stats_from_box(box)
        home_team_data = box.get('homeTeam', {})
        away_team_data = box.get('awayTeam', {})

        current_home = home_team_data.get('score', 0)
        current_away = away_team_data.get('score', 0)
        period = box.get('period', 0)
    except Exception as e:
        logger.warning(f"Could not fetch live game data: {e}")
        h1_home, h1_away = pred.h1_home, pred.h1_away
        current_home, current_away = int(pred.pred_final_home), int(pred.pred_final_away)
        period = 0
        eff = {}

    # Analyze markets
    total_rec = _analyze_total(
        pred.pred_final_total,
        odds_snapshot.total_points,
        odds_snapshot.total_over_odds or -110,
        odds_snapshot.total_under_odds or -110
    )

    spread_rec = _analyze_spread(
        pred.pred_final_margin,
        odds_snapshot.spread_home,
        odds_snapshot.spread_home_odds or -110,
        odds_snapshot.spread_away_odds or -110,
        pred.home_team,
        pred.away_team
    )

    # Determine best bet
    best_bet = None
    if total_rec.ev > 0 or spread_rec.ev > 0:
        best_bet = total_rec if total_rec.ev > spread_rec.ev else spread_rec

    # Create report object
    report = PredictionReport(
        game_id=game_id,
        away_team=pred.away_team,
        home_team=pred.home_team,
        current_period=period,
        current_away_score=current_away,
        current_home_score=current_home,
        halftime_away=pred.h1_away,
        halftime_home=pred.h1_home,
        pred_final_away=pred.pred_final_away,
        pred_final_home=pred.pred_final_home,
        pred_total=pred.pred_final_total,
        pred_margin=pred.pred_final_margin,
        home_win_prob=pred.home_win_prob,
        away_win_prob=pred.away_win_prob,
        total_q10=pred.total_q10,
        total_q90=pred.total_q90,
        margin_q10=pred.margin_q10,
        margin_q90=pred.margin_q90,
        home_efg=eff.get('home_efg', 0.52),
        away_efg=eff.get('away_efg', 0.52),
        home_tor=eff.get('home_tor', 0.12),
        away_tor=eff.get('away_tor', 0.12),
        line_total=odds_snapshot.total_points,
        total_over_odds=odds_snapshot.total_over_odds or -110,
        total_under_odds=odds_snapshot.total_under_odds or -110,
        line_spread=odds_snapshot.spread_home,
        spread_home_odds=odds_snapshot.spread_home_odds or -110,
        spread_away_odds=odds_snapshot.spread_away_odds or -110,
        moneyline_home=odds_snapshot.moneyline_home,
        moneyline_away=odds_snapshot.moneyline_away,
        bookmaker=odds_snapshot.bookmaker or "DraftKings",
        total_rec=total_rec,
        spread_rec=spread_rec,
        best_bet=best_bet
    )

    # Format output
    if format == "compact":
        return _format_compact(report)
    else:
        return _format_full(report)


def _format_full(r: PredictionReport) -> str:
    """Generate FULL format report matching the standard template."""
    lines = []

    # Header
    lines.append("")
    lines.append(f"🔥 {r.away_team} @ {r.home_team}: EV ANALYSIS")
    lines.append("─" * 50)
    lines.append("")

    # Market Odds Table
    lines.append("📊 Market Odds")
    lines.append("")
    lines.append("┌─────────────┬──────────┬──────┬────────┐")
    lines.append("│ Bet         │ Line     │ Odds │ Payout │")
    lines.append("├─────────────┼──────────┼──────┼────────┤")

    # Spread rows
    if r.line_spread > 0:
        lines.append(f"│ Spread      │ {r.home_team} +{r.line_spread:.1f} │ {r.spread_home_odds:+d} │ {r.spread_rec.payout:.3f}x │")
        lines.append(f"│ Spread      │ {r.away_team} -{r.line_spread:.1f} │ {r.spread_away_odds:+d} │ {1+100/abs(r.spread_away_odds):.3f}x │")
    else:
        lines.append(f"│ Spread      │ {r.home_team} {r.line_spread:+.1f} │ {r.spread_home_odds:+d} │ {r.spread_rec.payout:.3f}x │")
        lines.append(f"│ Spread      │ {r.away_team} +{abs(r.line_spread):.1f} │ {r.spread_away_odds:+d} │ {1+100/abs(r.spread_away_odds):.3f}x │")

    # Total rows
    lines.append(f"│ Total Over  │ {r.line_total:.1f}    │ {r.total_over_odds:+d} │ {1+100/abs(r.total_over_odds):.3f}x │")
    lines.append(f"│ Total Under │ {r.line_total:.1f}    │ {r.total_under_odds:+d} │ {1+100/abs(r.total_under_odds):.3f}x │")
    lines.append("└─────────────┴──────────┴──────┴────────┘")
    lines.append("")

    # Reptar Prediction Table
    lines.append("🎯 Reptar Prediction")
    lines.append("")
    lines.append("┌──────────────────┬──────────────────┐")
    lines.append("│ Metric           │ Value            │")
    lines.append("├──────────────────┼──────────────────┤")
    lines.append(f"│ Predicted Total  │ {r.pred_total:.1f}            │")

    # Margin description
    if r.pred_margin > 0:
        margin_desc = f"{r.home_team} wins by {r.pred_margin:.1f}"
    else:
        margin_desc = f"{r.away_team} wins by {abs(r.pred_margin):.1f}"
    lines.append(f"│ Predicted Margin │ {margin_desc:<16} │")
    lines.append("└──────────────────┴──────────────────┘")
    lines.append("")

    # Spread Analysis
    lines.append(f"🔥 SPREAD ANALYSIS")
    lines.append("─" * 50)
    lines.append("")
    lines.append("┌─────────────────────────────┬──────────────────────┐")
    lines.append("│ Metric                      │ Value                │")
    lines.append("├─────────────────────────────┼──────────────────────┤")

    # Spread line description
    if r.line_spread > 0:
        spread_line_desc = f"{r.home_team} +{r.line_spread:.1f} ({r.away_team} -{r.line_spread:.1f})"
    else:
        spread_line_desc = f"{r.home_team} {r.line_spread:+.1f} ({r.away_team} +{abs(r.line_spread):.1f})"

    lines.append(f"│ Line                        │ {spread_line_desc:<20} │")
    lines.append(f"│ Our Prediction              │ {margin_desc:<20} │")
    lines.append(f"│ Edge                        │ {r.spread_rec.edge:+.1f} points             │")
    lines.append(f"│ Edge in Sigma               │ {r.spread_rec.edge_sigma:.2f}x                 │")
    lines.append(f"│ Probability {r.spread_rec.side_desc:<17}│ {r.spread_rec.probability:.2f}%               │")
    lines.append(f"│ Odds                        │ {r.spread_rec.odds} ({r.spread_rec.payout:.3f}x payout) │")

    ev_icon = "✅" if r.spread_rec.ev > 0 else "❌"
    lines.append(f"│ EV                          │ {r.spread_rec.ev:+.2f}% {ev_icon:<13}│")
    lines.append("└─────────────────────────────┴──────────────────────┘")
    lines.append("")

    # Spread analysis text
    if r.spread_rec.ev > 0:
        lines.append(f"Analysis: {r.spread_rec.selection} has a {r.spread_rec.edge:+.1f} point edge with {r.spread_rec.probability:.1f}% probability. Positive EV!")
    else:
        lines.append(f"Analysis: {r.spread_rec.selection} has a {r.spread_rec.edge:+.1f} point edge, but {r.spread_rec.odds} odds make it {r.spread_rec.ev:+.2f}% EV.")
    lines.append("")

    # Total Analysis
    lines.append(f"🔥 TOTAL ANALYSIS")
    lines.append("─" * 50)
    lines.append("")
    lines.append("┌────────────────────────┬──────────────────────┐")
    lines.append("│ Metric                 │ Value                │")
    lines.append("├────────────────────────┼──────────────────────┤")
    lines.append(f"│ Line                   │ {r.line_total:<20} │")
    lines.append(f"│ Our Prediction         │ {r.pred_total:<20} │")

    total_direction = "OVER" if r.total_rec.edge > 0 else "UNDER"
    lines.append(f"│ Edge                   │ {r.total_rec.edge:+.1f} points ({total_direction})   │")
    lines.append(f"│ Edge in Sigma          │ {r.total_rec.edge_sigma:.2f}x                 │")
    lines.append(f"│ Probability {r.total_rec.side_desc:<13}│ {r.total_rec.probability:.2f}%               │")
    lines.append(f"│ Odds                   │ {r.total_rec.odds} ({r.total_rec.payout:.3f}x payout) │")

    ev_icon = "✅" if r.total_rec.ev > 0 else "❌"
    lines.append(f"│ EV                     │ {r.total_rec.ev:+.2f}% {ev_icon:<15}│")
    lines.append("└────────────────────────┴──────────────────────┘")
    lines.append("")

    # Total analysis text
    if r.total_rec.ev > 0:
        lines.append(f"Analysis: {r.total_rec.selection} has a {abs(r.total_rec.edge):.1f} point edge with {r.total_rec.probability:.1f}% probability. Positive EV!")
    else:
        if r.total_rec.edge > 0:
            lines.append(f"Analysis: OVER has {r.total_rec.edge:+.1f} points edge, but odds of {r.total_rec.odds} make it {r.total_rec.ev:+.2f}% EV.")
        else:
            lines.append(f"Analysis: UNDER has {abs(r.total_rec.edge):.1f} point edge (wrong direction) with only {r.total_rec.probability:.1f}% chance to hit.")
    lines.append("")

    # Final Recommendation
    rec_icon = "✅" if (r.total_rec.ev > 0 or r.spread_rec.ev > 0) else "❌"
    rec_text = "BET" if (r.total_rec.ev > 0 or r.spread_rec.ev > 0) else "PASS ON BOTH"

    lines.append(f"{rec_icon} FINAL RECOMMENDATION: {rec_text}")
    lines.append("─" * 50)
    lines.append("")

    # Summary Table
    lines.append("Summary Table")
    lines.append("")
    lines.append("┌─────────────┬──────────┬───────────┬─────────────┬──────┬─────────┬─────────┐")
    lines.append("│ Bet         │ Line     │ Edge      │ Probability │ Odds │ EV      │ Action  │")
    lines.append("├─────────────┼──────────┼───────────┼─────────────┼──────┼─────────┼─────────┤")

    spread_action_icon = "✅ BET" if r.spread_rec.ev > 0 else "❌ PASS"
    total_action_icon = "✅ BET" if r.total_rec.ev > 0 else "❌ PASS"

    # Spread row
    if r.line_spread > 0:
        spread_line_str = f"{r.home_team} +{r.line_spread:.1f}"
    else:
        spread_line_str = f"{r.home_team} {r.line_spread:+.1f}"

    lines.append(f"│ {r.spread_rec.selection:<11} │ {spread_line_str:<8} │ {r.spread_rec.edge:+.1f} pts  │ {r.spread_rec.probability:5.1f}%      │ {r.spread_rec.odds:+4d} │ {r.spread_rec.ev:+6.2f}% │ {spread_action_icon:<7} │")

    # Total row
    lines.append(f"│ {r.total_rec.selection:<11} │ {r.line_total:<8} │ {r.total_rec.edge:+.1f} pts  │ {r.total_rec.probability:5.1f}%      │ {r.total_rec.odds:+4d} │ {r.total_rec.ev:+6.2f}% │ {total_action_icon:<7} │")
    lines.append("└─────────────┴──────────┴───────────┴─────────────┴──────┴─────────┴─────────┘")
    lines.append("")

    # Why PASS? section (only if both are negative EV)
    if r.spread_rec.ev <= 0 and r.total_rec.ev <= 0:
        lines.append("❌ Why PASS?")
        lines.append("─" * 50)
        lines.append("")
        lines.append(f"1. Spread: {r.spread_rec.selection} ({r.spread_rec.odds})")
        lines.append(f"   • Edge: {r.spread_rec.edge:+.1f} points")
        if r.spread_rec.ev > -20:
            lines.append(f"   • But odds of {r.spread_rec.odds} kill the value - {r.spread_rec.ev:+.2f}% EV")
        else:
            lines.append(f"   • {r.spread_rec.ev:+.2f}% EV (losing bet)")
        lines.append(f"   • {r.home_team} has a {r.spread_rec.probability:.1f}% chance to cover")
        lines.append("")
        lines.append(f"2. Total: {r.total_rec.selection} ({r.total_rec.odds})")
        lines.append(f"   • Edge: {r.total_rec.edge:+.1f} points ({'wrong direction' if r.total_rec.edge < 0 else 'correct direction'})")
        lines.append(f"   • Only {r.total_rec.probability:.1f}% chance to hit")
        lines.append(f"   • {r.total_rec.ev:+.2f}% EV")
        lines.append("")
        lines.append("3. Overall")
        lines.append("   • No positive edge on either market")
        lines.append("   • Market has priced this game very efficiently")
        lines.append("   • Better to save your money for a better spot")
        lines.append("")

    # Perry's Take
    lines.append("🐶 Perry's Take")
    lines.append("─" * 50)
    lines.append("")

    period_str = f"Q{r.current_period}" if r.current_period <= 4 else f"OT{r.current_period - 4}"
    score_diff = abs(r.current_away_score - r.current_home_score)
    leader = r.away_team if r.current_away_score > r.current_home_score else r.home_team

    max_ev = max(r.total_rec.ev, r.spread_rec.ev)

    if max_ev <= 0:
        lines.append(f"This game is a STAY AWAY situation! 🛑")
        lines.append("")
        lines.append("Why:")
        if r.spread_rec.ev < 0 and abs(r.spread_rec.edge) > 3:
            lines.append(f"• Spread has edge ({r.spread_rec.edge:+.1f}) but heavy juice makes it -EV ({r.spread_rec.ev:+.2f}%)")
        else:
            lines.append(f"• Spread: {r.spread_rec.ev:+.2f}% EV (losing bet)")
        lines.append(f"• Total: {r.total_rec.ev:+.2f}% EV (losing bet)")
        lines.append("")
        lines.append("Key Observations:")
        lines.append(f"• {r.away_team} @ {r.home_team} in {period_str}")
        lines.append(f"• Current score: {r.away_team} {r.current_away_score} - {r.home_team} {r.current_home_score}")
        lines.append(f"• Reptar predicts {r.pred_total:.1f} total points")
        lines.append(f"• Market line of {r.line_total} is {'higher' if r.line_total > r.pred_total else 'lower'} than our prediction")
        lines.append("")
        lines.append("Recommendation:")
        lines.append("• ✅ PASS on both spread and total")
        lines.append("• 💰 Save your money for a better opportunity")
        lines.append("• 🎯 Wait for a game with larger discrepancy")
    else:
        lines.append(f"This game has VALUE! ✅")
        lines.append("")
        if r.best_bet:
            lines.append(f"Best Bet: {r.best_bet.selection} @ {r.best_bet.odds}")
            lines.append(f"• Edge: {r.best_bet.edge:+.1f} points")
            lines.append(f"• Probability: {r.best_bet.probability:.1f}%")
            lines.append(f"• EV: {r.best_bet.ev:+.2f}%")
        lines.append("")
        lines.append("Key Observations:")
        lines.append(f"• {r.away_team} @ {r.home_team} in {period_str}")
        lines.append(f"• Current score: {r.away_team} {r.current_away_score} - {r.home_team} {r.current_home_score}")
        lines.append(f"• Reptar predicts {r.pred_total:.1f} total points")
        lines.append(f"• Model edge of {r.best_bet.edge:+.1f} points on {r.best_bet.selection}")

    lines.append("")
    lines.append("─" * 50)
    lines.append("")
    lines.append("📝 Summary")
    lines.append("─" * 50)
    lines.append("")
    lines.append(f"{r.away_team} @ {r.home_team}:")
    lines.append("┌────────────────────────────────────────────────────┐")
    lines.append("│ Bet           │ Line   │ Edge    │ Prob  │ Odds  │ EV     │")
    lines.append("├────────────────────────────────────────────────────┤")
    lines.append(f"│ {r.spread_rec.selection:<13} │ {spread_line_str:<6} │ {r.spread_rec.edge:+.1f} pts│ {r.spread_rec.probability:5.1f}%│ {r.spread_rec.odds:+4d} │ {r.spread_rec.ev:+6.1f}%│")
    lines.append(f"│ {r.total_rec.selection:<13} │ {r.line_total:<6} │ {r.total_rec.edge:+.1f} pts│ {r.total_rec.probability:5.1f}%│ {r.total_rec.odds:+4d} │ {r.total_rec.ev:+6.1f}%│")
    lines.append("└────────────────────────────────────────────────────┘")
    lines.append("")

    if r.best_bet:
        lines.append(f"BEST BET: {r.best_bet.selection} @ {r.best_bet.odds} ({r.best_bet.ev:+.2f}% EV) ✅")
    else:
        lines.append("OVERALL: ❌ PASS ON BOTH")

    lines.append("")
    lines.append("─" * 50)
    lines.append("")

    return "\n".join(lines)


def _format_compact(r: PredictionReport) -> str:
    """Generate COMPACT format report."""
    lines = []

    lines.append("─" * 50)
    lines.append(f"{r.away_team} @ {r.home_team}")
    lines.append(f"  Halftime: {r.away_team} {r.halftime_away} - {r.home_team} {r.halftime_home}")
    lines.append(f"  Prediction: {r.away_team} {r.pred_final_away:.0f} - {r.home_team} {r.pred_final_home:.0f}")
    lines.append(f"  Total: {r.pred_total:.1f}")
    lines.append(f"  Line: {r.line_total} | Spread: {r.home_team} {r.line_spread:+.1f}")

    if r.best_bet:
        lines.append(f"  Best: {r.best_bet.selection} ({r.best_bet.ev:+.2f}% EV)")
    else:
        lines.append(f"  Best: PASS")

    lines.append("─" * 50)

    return "\n".join(lines)


__all__ = ["generate_report", "ReportFormat", "PredictionReport", "BettingRecommendation"]

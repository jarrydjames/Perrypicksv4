"""
Daily Report Card Generator for PerryPicks

Generates end-of-day reports showing accuracy and ROI for:
- Recommended bets (all passing thresholds)
- High confidence bets (tier A/A+)
- Parlays (SGP)

Assumes $10 bet per pick for ROI calculation.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from dashboard.backend.database import (
    SessionLocal,
    BettingRecommendation,
    BetStatus,
    Parlay,
    ParlayLeg,
    Prediction,
    Game,
)

logger = logging.getLogger(__name__)


@dataclass
class CategoryStats:
    """Statistics for a bet category."""
    name: str
    total: int
    won: int
    lost: int
    push: int
    pending: int
    accuracy: float  # won / (won + lost + push)
    win_rate: float  # won / (won + lost), excludes pushes
    total_wagered: float
    total_return: float
    roi: float  # (total_return - total_wagered) / total_wagered


def calculate_payout(odds: int, stake: float = 10.0) -> float:
    """
    Calculate payout for American odds.

    Args:
        odds: American odds (e.g., -110, +150)
        stake: Bet amount in dollars

    Returns:
        Total payout (stake + profit) if bet wins
    """
    if odds > 0:
        # Positive odds: profit = stake * (odds / 100)
        profit = stake * (odds / 100)
    else:
        # Negative odds: profit = stake * (100 / abs(odds))
        profit = stake * (100 / abs(odds))

    return stake + profit


def get_recommended_bets_stats(db, date: datetime, trigger_type: Optional[str] = None) -> CategoryStats:
    """
    Get stats for all recommended bets (passing thresholds) for a given date.

    These are all BettingRecommendations that were posted (not passed on).
    """
    from sqlalchemy import text

    # Get all resolved recommendations from games played on the given date
    # Query by game_date, not prediction created_at
    start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    try:
        # Use raw SQL to query, avoiding enum mapping issues
        # IMPORTANT: Query by game_date so report reflects actual game results
        sql = """
            SELECT br.id, br.odds, br.result
            FROM betting_recommendations br
            JOIN predictions p ON br.prediction_id = p.id
            JOIN games g ON p.game_id = g.id
            WHERE g.game_date >= :start
            AND g.game_date < :end
        """
        params = {"start": start_of_day, "end": end_of_day}
        if trigger_type:
            sql += " AND p.trigger_type = :trigger_type"
            params["trigger_type"] = trigger_type

        result = db.execute(text(sql), params)

        rows = result.fetchall()
    except Exception as e:
        logger.warning(f"Query failed, returning empty stats: {e}")
        rows = []

    total = 0
    won = 0
    lost = 0
    push = 0
    pending = 0
    total_wagered = 0.0
    total_return = 0.0

    for row in rows:
        rec_id, odds, result = row

        # Normalize result to lowercase for comparison
        result_lower = (result or '').lower()

        # Skip pending
        if result_lower == 'pending':
            pending += 1
            continue

        total += 1
        total_wagered += 10.0  # $10 per bet

        if result_lower == 'won':
            won += 1
            # Calculate payout
            odds_val = odds if odds else -110
            total_return += calculate_payout(odds_val, 10.0)
        elif result_lower == 'lost':
            lost += 1
            # Lost bet = $0 return
        elif result_lower == 'push':
            push += 1
            # Push = get stake back
            total_return += 10.0

    # Calculate metrics - only if we have resolved bets
    decided = won + lost
    accuracy = won / total if total > 0 else 0.0
    win_rate = won / decided if decided > 0 else 0.0
    roi = (total_return - total_wagered) / total_wagered if total_wagered > 0 else 0.0
    profit = total_return - total_wagered if total > 0 else 0.0

    return CategoryStats(
        name="Recommended Bets",
        total=total,
        won=won,
        lost=lost,
        push=push,
        pending=pending,
        accuracy=accuracy,
        win_rate=win_rate,
        total_wagered=total_wagered,
        total_return=total_return,
        roi=roi,
    )


def get_high_confidence_stats(db, date: datetime, trigger_type: Optional[str] = None) -> CategoryStats:
    """
    Get stats for high confidence bets (tier A or A+) for a given date.
    """
    from sqlalchemy import text

    start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    try:
        # Use raw SQL to avoid enum mapping issues
        # IMPORTANT: Query by game_date so report reflects actual game results
        sql = """
            SELECT br.id, br.odds, br.result
            FROM betting_recommendations br
            JOIN predictions p ON br.prediction_id = p.id
            JOIN games g ON p.game_id = g.id
            WHERE g.game_date >= :start
            AND g.game_date < :end
            AND br.confidence_tier IN ('A', 'A+')
        """
        params = {"start": start_of_day, "end": end_of_day}
        if trigger_type:
            sql += " AND p.trigger_type = :trigger_type"
            params["trigger_type"] = trigger_type

        result = db.execute(text(sql), params)

        rows = result.fetchall()
    except Exception as e:
        logger.warning(f"Query failed, returning empty stats: {e}")
        rows = []

    total = 0
    won = 0
    lost = 0
    push = 0
    pending = 0
    total_wagered = 0.0
    total_return = 0.0

    for row in rows:
        rec_id, odds, result = row

        # Normalize result to lowercase for comparison
        result_lower = (result or '').lower()

        if result_lower == 'pending':
            pending += 1
            continue

        total += 1
        total_wagered += 10.0

        if result_lower == 'won':
            won += 1
            odds_val = odds if odds else -110
            total_return += calculate_payout(odds_val, 10.0)
        elif result_lower == 'lost':
            lost += 1
        elif result_lower == 'push':
            push += 1
            total_return += 10.0

    decided = won + lost
    accuracy = won / total if total > 0 else 0.0
    win_rate = won / decided if decided > 0 else 0.0
    roi = (total_return - total_wagered) / total_wagered if total_wagered > 0 else 0.0

    return CategoryStats(
        name="High Confidence",
        total=total,
        won=won,
        lost=lost,
        push=push,
        pending=pending,
        accuracy=accuracy,
        win_rate=win_rate,
        total_wagered=total_wagered,
        total_return=total_return,
        roi=roi,
    )


def get_parlay_stats(db, date: datetime, trigger_type: Optional[str] = None) -> CategoryStats:
    """
    Get stats for parlays (SGP) for a given date.

    A parlay wins only if ALL legs win.
    For ROI: parlay payout = product of individual odds converted to decimal.
    """
    from sqlalchemy import text

    start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    try:
        # Query parlays for games played on the given date
        # IMPORTANT: Query by game_date so report reflects actual game results
        sql = """
            SELECT p.id, p.result
            FROM parlays p
            JOIN games g ON p.game_id = g.id
            JOIN predictions pr ON p.prediction_id = pr.id
            WHERE g.game_date >= :start
            AND g.game_date < :end
        """
        params = {"start": start_of_day, "end": end_of_day}
        if trigger_type:
            sql += " AND pr.trigger_type = :trigger_type"
            params["trigger_type"] = trigger_type

        result = db.execute(text(sql), params)

        parlay_rows = result.fetchall()
    except Exception as e:
        logger.warning(f"Parlay query failed, returning empty stats: {e}")
        parlay_rows = []

    total = 0
    won = 0
    lost = 0
    push = 0
    pending = 0
    total_wagered = 0.0
    total_return = 0.0

    for parlay_row in parlay_rows:
        parlay_id, result = parlay_row

        # Normalize result to lowercase for comparison
        result_lower = (result or '').lower()

        if result_lower == 'pending':
            pending += 1
            continue

        total += 1
        total_wagered += 10.0

        if result_lower == 'won':
            won += 1
            # Calculate parlay payout from legs using raw SQL
            try:
                legs_result = db.execute(text("""
                    SELECT pl.odds
                    FROM parlay_legs pl
                    WHERE pl.parlay_id = :parlay_id
                """), {"parlay_id": parlay_id})

                parlay_multiplier = 1.0
                for leg_row in legs_result.fetchall():
                    leg_odds = leg_row[0] if leg_row[0] else -110
                    if leg_odds > 0:
                        multiplier = 1 + (leg_odds / 100)
                    else:
                        multiplier = 1 + (100 / abs(leg_odds))
                    parlay_multiplier *= multiplier
                total_return += 10.0 * parlay_multiplier
            except Exception:
                # Fallback: assume standard -110 odds for each leg
                leg_count_result = db.execute(text("""
                    SELECT COUNT(*) FROM parlay_legs WHERE parlay_id = :parlay_id
                """), {"parlay_id": parlay_id})
                leg_count = leg_count_result.fetchone()[0]
                # Each -110 leg multiplies by ~1.91
                parlay_multiplier = (1.91 ** leg_count)
                total_return += 10.0 * parlay_multiplier
        elif result_lower == 'lost':
            lost += 1
        elif result_lower == 'push':
            push += 1
            total_return += 10.0

    decided = won + lost
    accuracy = won / total if total > 0 else 0.0
    win_rate = won / decided if decided > 0 else 0.0
    roi = (total_return - total_wagered) / total_wagered if total_wagered > 0 else 0.0

    return CategoryStats(
        name="Parlays (SGP)",
        total=total,
        won=won,
        lost=lost,
        push=push,
        pending=pending,
        accuracy=accuracy,
        win_rate=win_rate,
        total_wagered=total_wagered,
        total_return=total_return,
        roi=roi,
    )


def generate_daily_report_card(date: Optional[datetime] = None) -> str:
    """
    Generate a daily report card for Discord.

    Args:
        date: Date to generate report for (defaults to today)

    Returns:
        Formatted report card string
    """
    if date is None:
        date = datetime.utcnow()

    db = SessionLocal()

    try:
        # Get stats for each category (split by trigger type)
        pregame_recommended = get_recommended_bets_stats(db, date, trigger_type="PREGAME")
        pregame_high_conf = get_high_confidence_stats(db, date, trigger_type="PREGAME")
        pregame_parlays = get_parlay_stats(db, date, trigger_type="PREGAME")

        halftime_recommended = get_recommended_bets_stats(db, date, trigger_type="HALFTIME")
        halftime_high_conf = get_high_confidence_stats(db, date, trigger_type="HALFTIME")
        halftime_parlays = get_parlay_stats(db, date, trigger_type="HALFTIME")

        # Combined (overall) for summary line
        recommended = get_recommended_bets_stats(db, date)
        high_conf = get_high_confidence_stats(db, date)
        parlays = get_parlay_stats(db, date)

        # Format date
        date_str = date.strftime("%B %d, %Y")

        # Build report
        lines = []
        lines.append(f"📊 **DAILY REPORT CARD**")
        lines.append(f"_{date_str}_")
        lines.append("")

        def render_section_block(title: str, rec: CategoryStats, hc: CategoryStats, sgp: CategoryStats) -> None:
            lines.append(title)
            lines.append("")

            section_wagered = rec.total_wagered + hc.total_wagered + sgp.total_wagered
            section_return = rec.total_return + hc.total_return + sgp.total_return
            section_roi = (
                (section_return - section_wagered) / section_wagered
                if section_wagered > 0
                else 0.0
            )
            lines.append(
                f"📈 Section ROI: **{section_roi:+.1%}** (${section_return - section_wagered:+.2f} on ${section_wagered:.0f})"
            )
            lines.append("")

            # Recommended Bets Section
            lines.append("🎯 **Recommended Bets**")
            if rec.total > 0:
                lines.append(f"   Record: {rec.won}W-{rec.lost}L-{rec.push}P")
                lines.append(f"   Accuracy: **{rec.accuracy:.1%}**")
                lines.append(
                    f"   ROI: **{rec.roi:+.1%}** (${rec.total_return - rec.total_wagered:+.2f} on ${rec.total_wagered:.0f})"
                )
            else:
                lines.append("   No resolved bets")
            lines.append("")

            # High Confidence Section
            lines.append("🔥 **High Confidence (Tier A)**")
            if hc.total > 0:
                lines.append(f"   Record: {hc.won}W-{hc.lost}L-{hc.push}P")
                lines.append(f"   Accuracy: **{hc.accuracy:.1%}**")
                lines.append(
                    f"   ROI: **{hc.roi:+.1%}** (${hc.total_return - hc.total_wagered:+.2f} on ${hc.total_wagered:.0f})"
                )
            else:
                lines.append("   No high confidence bets")
            lines.append("")

            # Parlays Section
            lines.append("💰 **Parlays (SGP)**")
            if sgp.total > 0:
                lines.append(f"   Record: {sgp.won}W-{sgp.lost}L-{sgp.push}P")
                lines.append(f"   Accuracy: **{sgp.accuracy:.1%}**")
                lines.append(
                    f"   ROI: **{sgp.roi:+.1%}** (${sgp.total_return - sgp.total_wagered:+.2f} on ${sgp.total_wagered:.0f})"
                )
            else:
                lines.append("   No parlays")
            lines.append("")

        render_section_block("🧠 **Pregame (MAXIMUS)**", pregame_recommended, pregame_high_conf, pregame_parlays)
        render_section_block("🔥 **Halftime (REPTAR)**", halftime_recommended, halftime_high_conf, halftime_parlays)

        # Summary
        total_wagered = recommended.total_wagered + high_conf.total_wagered + parlays.total_wagered
        total_return = recommended.total_return + high_conf.total_return + parlays.total_return
        overall_roi = (total_return - total_wagered) / total_wagered if total_wagered > 0 else 0.0

        lines.append("---")
        lines.append(f"📈 **Overall: {overall_roi:+.1%} ROI** (${total_return - total_wagered:+.2f})")
        lines.append("")
        lines.append("_PerryPicks | $10 unit assumption_")

        return "\n".join(lines)

    finally:
        db.close()


def save_parlay_from_recommendations(
    game_id: int,
    prediction_id: int,
    recommendations: List[dict],
    combined_probability: float,
) -> Optional[int]:
    """
    Save a parlay to the database when an SGP is posted.

    Args:
        game_id: Database game ID
        prediction_id: Database prediction ID
        recommendations: List of recommendation dicts that form the parlay
        combined_probability: Combined probability of all legs

    Returns:
        Parlay ID if saved, None otherwise
    """
    if len(recommendations) < 2:
        return None

    db = SessionLocal()

    try:
        # Create parlay
        parlay = Parlay(
            game_id=game_id,
            prediction_id=prediction_id,
            combined_probability=combined_probability,
            leg_count=len(recommendations),
            result=BetStatus.PENDING,
        )
        db.add(parlay)
        db.commit()
        db.refresh(parlay)

        # Create legs
        for rec in recommendations:
            # Find the matching BettingRecommendation
            bet_rec = db.query(BettingRecommendation).filter(
                BettingRecommendation.prediction_id == prediction_id,
                BettingRecommendation.pick == rec.get("pick"),
            ).first()

            if bet_rec:
                leg = ParlayLeg(
                    parlay_id=parlay.id,
                    recommendation_id=bet_rec.id,
                    pick=rec.get("pick", ""),
                    bet_type=rec.get("bet_type", ""),
                    line=rec.get("line"),
                    probability=rec.get("probability"),
                    edge=rec.get("edge"),
                    result=BetStatus.PENDING,
                )
                db.add(leg)

        db.commit()
        logger.info(f"Saved parlay {parlay.id} with {len(recommendations)} legs")
        return parlay.id

    except Exception as e:
        logger.error(f"Failed to save parlay: {e}")
        db.rollback()
        return None

    finally:
        db.close()


__all__ = [
    "generate_daily_report_card",
    "save_parlay_from_recommendations",
    "CategoryStats",
]

"""
Bet Resolution Service for PerryPicks

Automatically resolves betting recommendations and parlays after games complete.
Updates result from PENDING to WON/LOST/PUSH based on final scores.

Resolution Logic:
- TOTAL: Compare final total to line (over/under)
- SPREAD: Compare final margin to spread
- MONEYLINE: Check which team won
- TEAM_TOTAL: Compare team score to line (over/under)

Parlay Resolution:
- Parlay wins only if ALL legs win
- Parlay loses if ANY leg loses
- Parlay pushes if no losses and at least one push
"""

import logging
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import text

logger = logging.getLogger(__name__)


def resolve_total_bet(
    final_total: float,
    line: float,
    pick: str,
) -> str:
    """
    Resolve a total (over/under) bet.

    Args:
        final_total: Final combined score
        line: The betting line
        pick: "OVER X" or "UNDER X"

    Returns:
        "won", "lost", or "push"
    """
    pick_upper = pick.upper()

    if final_total > line:
        # Final total is OVER the line
        if "OVER" in pick_upper:
            return "won"
        elif "UNDER" in pick_upper:
            return "lost"
    elif final_total < line:
        # Final total is UNDER the line
        if "UNDER" in pick_upper:
            return "won"
        elif "OVER" in pick_upper:
            return "lost"
    else:
        # Exact push
        return "push"

    return "lost"  # Default fallback


def resolve_spread_bet(
    final_home_score: float,
    final_away_score: float,
    spread: float,
    pick: str,
    home_team: str,
    away_team: str,
) -> str:
    """
    Resolve a spread bet.

    Args:
        final_home_score: Home team final score
        final_away_score: Away team final score
        spread: The spread (positive = home favored, e.g., -5.5 means home -5.5)
        pick: "HOME -5.5" or "AWAY +5.5" or team-specific like "BOS -5.5"
        home_team: Home team tricode
        away_team: Away team tricode

    Returns:
        "won", "lost", or "push"
    """
    pick_upper = pick.upper()
    final_margin = final_home_score - final_away_score  # Positive = home winning

    # Determine which team the pick is for
    is_home_pick = (
        home_team.upper() in pick_upper or
        "HOME" in pick_upper
    )
    is_away_pick = (
        away_team.upper() in pick_upper or
        "AWAY" in pick_upper
    )

    # Parse the spread from the pick (e.g., "BOS -5.5" -> -5.5)
    pick_spread = spread  # Default to the line spread
    pick_parts = pick_upper.split()
    for part in pick_parts:
        try:
            pick_spread = float(part.replace("+", ""))
            break
        except ValueError:
            continue

    if is_home_pick:
        # Home spread: home covers if (home_score + spread) > away_score
        adjusted = (final_home_score + pick_spread) - final_away_score
        if adjusted > 0:
            return "won"
        elif adjusted < 0:
            return "lost"
        return "push"

    elif is_away_pick:
        # Away spread: away covers if (away_score + spread) > home_score
        adjusted = (final_away_score + pick_spread) - final_home_score
        if adjusted > 0:
            return "won"
        elif adjusted < 0:
            return "lost"
        return "push"
    else:
        logger.warning(f"Could not determine team from pick: {pick}")
        return "lost"


def resolve_moneyline_bet(
    final_home_score: float,
    final_away_score: float,
    pick: str,
    home_team: str,
    away_team: str,
) -> str:
    """
    Resolve a moneyline bet.

    Args:
        final_home_score: Home team final score
        final_away_score: Away team final score
        pick: "HOME ML" or "AWAY ML" or team-specific like "BOS ML"
        home_team: Home team tricode
        away_team: Away team tricode

    Returns:
        "won" or "lost" (no pushes in ML)
    """
    pick_upper = pick.upper()
    home_won = final_home_score > final_away_score
    away_won = final_away_score > final_home_score

    # Determine which team the pick is for
    is_home_pick = (
        home_team.upper() in pick_upper or
        "HOME" in pick_upper
    )
    is_away_pick = (
        away_team.upper() in pick_upper or
        "AWAY" in pick_upper
    )

    if is_home_pick and home_won:
        return "won"
    elif is_away_pick and away_won:
        return "won"
    else:
        return "lost"


def resolve_team_total_bet(
    final_home_score: float,
    final_away_score: float,
    line: float,
    pick: str,
    home_team: str,
    away_team: str,
) -> str:
    """
    Resolve a team total bet.

    Args:
        final_home_score: Home team final score
        final_away_score: Away team final score
        line: The team total line
        pick: "BOS OVER 115.5" or "LAL UNDER 110.5"
        home_team: Home team tricode
        away_team: Away team tricode

    Returns:
        "won", "lost", or "push"
    """
    pick_upper = pick.upper()

    # Determine which team
    is_home = home_team.upper() in pick_upper
    is_away = away_team.upper() in pick_upper

    team_score = final_home_score if is_home else final_away_score if is_away else None

    if team_score is None:
        logger.warning(f"Could not determine team from team total pick: {pick}")
        return "lost"

    is_over = "OVER" in pick_upper
    is_under = "UNDER" in pick_upper

    if team_score > line:
        if is_over:
            return "won"
        elif is_under:
            return "lost"
    elif team_score < line:
        if is_under:
            return "won"
        elif is_over:
            return "lost"
    else:
        return "push"

    return "lost"


def resolve_betting_recommendation(
    rec_id: int,
    bet_type: str,
    pick: str,
    line: Optional[float],
    final_home_score: float,
    final_away_score: float,
    home_team: str,
    away_team: str,
) -> str:
    """
    Resolve a single betting recommendation.

    Args:
        rec_id: Recommendation ID (for logging)
        bet_type: "total", "spread", "moneyline", or "team_total"
        pick: The pick string
        line: The betting line (if applicable)
        final_home_score: Final home score
        final_away_score: Final away score
        home_team: Home team tricode
        away_team: Away team tricode

    Returns:
        "won", "lost", or "push"
    """
    bet_type_lower = (bet_type or "").lower()
    final_total = final_home_score + final_away_score

    if bet_type_lower == "total":
        if line is None:
            logger.warning(f"Rec {rec_id}: No line for total bet")
            return "lost"
        result = resolve_total_bet(final_total, line, pick)

    elif bet_type_lower == "spread":
        if line is None:
            logger.warning(f"Rec {rec_id}: No line for spread bet")
            return "lost"
        result = resolve_spread_bet(
            final_home_score, final_away_score, line, pick, home_team, away_team
        )

    elif bet_type_lower in ("moneyline", "ml"):
        result = resolve_moneyline_bet(
            final_home_score, final_away_score, pick, home_team, away_team
        )

    elif bet_type_lower == "team_total":
        if line is None:
            logger.warning(f"Rec {rec_id}: No line for team total bet")
            return "lost"
        result = resolve_team_total_bet(
            final_home_score, final_away_score, line, pick, home_team, away_team
        )

    else:
        logger.warning(f"Rec {rec_id}: Unknown bet type: {bet_type}")
        result = "lost"

    return result


def resolve_parlay_from_legs(leg_results: List[str]) -> str:
    """
    Resolve a parlay based on leg results.

    Rules:
    - Parlay WINS if ALL legs win
    - Parlay LOSES if ANY leg loses
    - Parlay PUSHES if no losses and at least one push

    Args:
        leg_results: List of leg results ("won", "lost", "push")

    Returns:
        "won", "lost", or "push"
    """
    if not leg_results:
        return "lost"

    has_loss = "lost" in leg_results
    has_push = "push" in leg_results
    all_won = all(r == "won" for r in leg_results)

    if has_loss:
        return "lost"
    elif all_won:
        return "won"
    elif has_push:
        return "push"
    else:
        return "lost"


def resolve_completed_games(db) -> Tuple[int, int, int]:
    """
    Resolve all betting recommendations for completed games.

    This function:
    1. Finds games with status "Final" that have unresolved bets
    2. Resolves each betting recommendation
    3. Updates the result in the database
    4. Resolves parlays based on leg results

    Args:
        db: Database session

    Returns:
        Tuple of (resolved_bets, resolved_parlays, errors)
    """
    resolved_bets = 0
    resolved_parlays = 0
    errors = 0

    try:
        # Find completed games with final scores
        completed_games = db.execute(text("""
            SELECT DISTINCT g.id, g.home_team, g.away_team, g.final_home_score, g.final_away_score
            FROM games g
            WHERE g.game_status = 'Final'
            AND g.final_home_score IS NOT NULL
            AND g.final_away_score IS NOT NULL
            AND g.final_home_score > 0
            AND g.final_away_score > 0
        """)).fetchall()

        if not completed_games:
            logger.debug("No completed games found for resolution")
            return (0, 0, 0)

        logger.info(f"Found {len(completed_games)} completed games to check for bet resolution")

        for game in completed_games:
            game_id, home_team, away_team, final_home, final_away = game

            # Skip if scores are None
            if final_home is None or final_away is None:
                continue

            # Find pending betting recommendations for this game
            pending_recs = db.execute(text("""
                SELECT br.id, br.bet_type, br.pick, br.line, br.result
                FROM betting_recommendations br
                JOIN predictions p ON br.prediction_id = p.id
                WHERE p.game_id = :game_id
                AND br.result = 'PENDING'
            """), {"game_id": game_id}).fetchall()

            if not pending_recs:
                continue

            logger.info(f"Resolving {len(pending_recs)} pending bets for {away_team}@{home_team} ({final_away}-{final_home})")

            for rec in pending_recs:
                rec_id, bet_type, pick, line, current_result = rec

                try:
                    result = resolve_betting_recommendation(
                        rec_id=rec_id,
                        bet_type=bet_type,
                        pick=pick or "",
                        line=line,
                        final_home_score=float(final_home),
                        final_away_score=float(final_away),
                        home_team=home_team or "HOME",
                        away_team=away_team or "AWAY",
                    )

                    # Update the database (uppercase for enum)
                    db.execute(text("""
                        UPDATE betting_recommendations
                        SET result = :result
                        WHERE id = :rec_id
                    """), {"result": result.upper(), "rec_id": rec_id})

                    resolved_bets += 1
                    logger.info(f"  Rec #{rec_id} ({bet_type}: {pick}) -> {result.upper()}")

                except Exception as e:
                    logger.error(f"  Failed to resolve rec #{rec_id}: {e}")
                    errors += 1

            # Now resolve parlays for this game
            pending_parlays = db.execute(text("""
                SELECT p.id
                FROM parlays p
                WHERE p.game_id = :game_id
                AND p.result = 'PENDING'
            """), {"game_id": game_id}).fetchall()

            for parlay_row in pending_parlays:
                parlay_id = parlay_row[0]

                try:
                    # Get all legs for this parlay
                    legs = db.execute(text("""
                        SELECT pl.id, pl.pick, pl.bet_type, pl.line
                        FROM parlay_legs pl
                        WHERE pl.parlay_id = :parlay_id
                    """), {"parlay_id": parlay_id}).fetchall()

                    if not legs:
                        continue

                    leg_results = []
                    for leg in legs:
                        leg_id, leg_pick, leg_bet_type, leg_line = leg

                        leg_result = resolve_betting_recommendation(
                            rec_id=leg_id,
                            bet_type=leg_bet_type,
                            pick=leg_pick or "",
                            line=leg_line,
                            final_home_score=float(final_home),
                            final_away_score=float(final_away),
                            home_team=home_team or "HOME",
                            away_team=away_team or "AWAY",
                        )

                        # Update leg result (uppercase for enum)
                        db.execute(text("""
                            UPDATE parlay_legs
                            SET result = :result
                            WHERE id = :leg_id
                        """), {"result": leg_result.upper(), "leg_id": leg_id})

                        leg_results.append(leg_result)

                    # Resolve parlay based on legs
                    parlay_result = resolve_parlay_from_legs(leg_results)

                    # Update parlay result (uppercase for enum)
                    db.execute(text("""
                        UPDATE parlays
                        SET result = :result, resolved_at = :resolved_at
                        WHERE id = :parlay_id
                    """), {
                        "result": parlay_result.upper(),
                        "resolved_at": datetime.utcnow(),
                        "parlay_id": parlay_id
                    })

                    resolved_parlays += 1
                    logger.info(f"  Parlay #{parlay_id} ({len(legs)} legs) -> {parlay_result.upper()}")

                except Exception as e:
                    logger.error(f"  Failed to resolve parlay #{parlay_id}: {e}")
                    errors += 1

        # Commit all changes
        db.commit()

        if resolved_bets > 0 or resolved_parlays > 0:
            logger.info(f"Bet resolution complete: {resolved_bets} bets, {resolved_parlays} parlays resolved, {errors} errors")

        return (resolved_bets, resolved_parlays, errors)

    except Exception as e:
        logger.error(f"Bet resolution failed: {e}")
        db.rollback()
        return (0, 0, 1)


def run_bet_resolution() -> Tuple[int, int, int]:
    """
    Main entry point for bet resolution.
    Creates a database session and runs resolution.

    Returns:
        Tuple of (resolved_bets, resolved_parlays, errors)
    """
    from dashboard.backend.database import SessionLocal

    db = SessionLocal()
    try:
        return resolve_completed_games(db)
    finally:
        db.close()


__all__ = [
    "resolve_total_bet",
    "resolve_spread_bet",
    "resolve_moneyline_bet",
    "resolve_team_total_bet",
    "resolve_betting_recommendation",
    "resolve_parlay_from_legs",
    "resolve_completed_games",
    "run_bet_resolution",
]

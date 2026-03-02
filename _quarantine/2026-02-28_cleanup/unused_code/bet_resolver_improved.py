"""
Improved Bet Resolution Service with line parsing from pick strings.
"""

import re
import logging
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import text

logger = logging.getLogger(__name__)


def parse_line_from_pick(pick: str) -> Optional[float]:
    """
    Parse the line value from a pick string.
    
    Handles patterns like:
    - "OVER 226.5" -> 226.5
    - "UNDER 202.5" -> 202.5
    - "BOS -5.5" -> -5.5
    - "LAL +7.5" -> 7.5
    - "CLE ML" -> None (no line)
    """
    if not pick:
        return None
    
    # Try to extract number from pick string
    # This regex matches: optional sign, digits, optional decimal
    numbers = re.findall(r'[-+]?\d+\.?\d*', pick)
    
    if numbers:
        try:
            return float(numbers[0])
        except (ValueError, IndexError):
            return None
    
    return None


def resolve_total_bet(
    final_total: float,
    line: float,
    pick: str,
) -> str:
    """
    Resolve a total (over/under) bet.
    
    If line is None, attempts to parse from pick string.
    """
    # Parse line from pick if not provided
    if line is None:
        line = parse_line_from_pick(pick)
        if line is None:
            logger.warning(f"Could not parse line from pick: {pick}")
            return "lost"
    
    pick_upper = pick.upper()

    if final_total > line:
        if "OVER" in pick_upper:
            return "won"
        elif "UNDER" in pick_upper:
            return "lost"
    elif final_total < line:
        if "UNDER" in pick_upper:
            return "won"
        elif "OVER" in pick_upper:
            return "lost"
    else:
        return "push"

    return "lost"


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
    
    If spread is None, attempts to parse from pick string.
    """
    # Parse spread from pick if not provided
    if spread is None:
        spread = parse_line_from_pick(pick)
        if spread is None:
            logger.warning(f"Could not parse spread from pick: {pick}")
            return "lost"
    
    pick_upper = pick.upper()
    final_margin = final_home_score - final_away_score

    is_home_pick = (
        home_team.upper() in pick_upper or
        "HOME" in pick_upper
    )
    is_away_pick = (
        away_team.upper() in pick_upper or
        "AWAY" in pick_upper
    )

    if is_home_pick:
        adjusted_margin = final_margin + spread
        if adjusted_margin > 0:
            return "won"
        elif adjusted_margin < 0:
            return "lost"
        else:
            return "push"
    elif is_away_pick:
        adjusted_margin = final_margin + spread
        if adjusted_margin < 0:
            return "won"
        elif adjusted_margin > 0:
            return "lost"
        else:
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
    """Resolve a moneyline bet."""
    pick_upper = pick.upper()
    home_won = final_home_score > final_away_score
    away_won = final_away_score > final_home_score

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
    
    If line is None, attempts to parse from pick string.
    """
    # Parse line from pick if not provided
    if line is None:
        line = parse_line_from_pick(pick)
        if line is None:
            logger.warning(f"Could not parse line from pick: {pick}")
            return "lost"
    
    pick_upper = pick.upper()

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
    
    Now with improved line parsing from pick strings.
    """
    bet_type_lower = (bet_type or "").lower()
    final_total = final_home_score + final_away_score

    if bet_type_lower == "total":
        result = resolve_total_bet(final_total, line, pick)

    elif bet_type_lower == "spread":
        result = resolve_spread_bet(
            final_home_score, final_away_score, line, pick, home_team, away_team
        )

    elif bet_type_lower in ("moneyline", "ml"):
        result = resolve_moneyline_bet(
            final_home_score, final_away_score, pick, home_team, away_team
        )

    elif bet_type_lower == "team_total":
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


__all__ = [
    "parse_line_from_pick",
    "resolve_total_bet",
    "resolve_spread_bet",
    "resolve_moneyline_bet",
    "resolve_team_total_bet",
    "resolve_betting_recommendation",
    "resolve_parlay_from_legs",
]

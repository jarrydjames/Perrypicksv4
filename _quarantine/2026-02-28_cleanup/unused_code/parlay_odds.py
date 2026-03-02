"""
Calculate combined parlay odds from individual leg odds.
"""


def american_to_decimal(odds: int) -> float:
    """
    Convert American odds to decimal odds.
    
    Examples:
        -110 -> 1.91
        +150 -> 2.50
        -200 -> 1.50
    """
    if odds > 0:
        return 1 + (odds / 100)
    else:
        return 1 + (100 / abs(odds))


def decimal_to_american(decimal_odds: float) -> int:
    """
    Convert decimal odds to American odds.
    
    Examples:
        1.91 -> -110
        2.50 -> +150
        1.50 -> -200
    """
    if decimal_odds >= 2.0:
        return int((decimal_odds - 1) * 100)
    else:
        return int(-100 / (decimal_odds - 1))


def calculate_combined_odds(leg_odds: list) -> int:
    """
    Calculate combined parlay odds from individual leg odds.
    
    Args:
        leg_odds: List of American odds for each leg (e.g., [-110, -110, +150])
        
    Returns:
        Combined American odds for the parlay
        
    Example:
        [-110, -110] -> roughly +264
        [-110, -110, -110] -> roughly +597
    """
    if not leg_odds:
        return -110  # Default
    
    # Convert all to decimal
    decimal_multiplier = 1.0
    for odds in leg_odds:
        if odds is None:
            odds = -110  # Default if missing
        decimal_multiplier *= american_to_decimal(odds)
    
    # Convert back to American
    return decimal_to_american(decimal_multiplier)


def format_american_odds(odds: int) -> str:
    """
    Format American odds for display.
    
    Examples:
        -110 -> "-110"
        +150 -> "+150"
    """
    if odds > 0:
        return f"+{odds}"
    else:
        return str(odds)


def calculate_parlay_payout(stake: float, leg_odds: list) -> dict:
    """
    Calculate potential parlay payout.
    
    Args:
        stake: Bet amount in dollars
        leg_odds: List of American odds for each leg
        
    Returns:
        Dictionary with payout details
    """
    combined_odds = calculate_combined_odds(leg_odds)
    
    # Calculate payout
    if combined_odds > 0:
        profit = stake * (combined_odds / 100)
    else:
        profit = stake * (100 / abs(combined_odds))
    
    total_return = stake + profit
    
    return {
        "leg_odds": leg_odds,
        "combined_odds": combined_odds,
        "combined_odds_str": format_american_odds(combined_odds),
        "stake": stake,
        "profit": profit,
        "total_return": total_return,
    }


__all__ = [
    "american_to_decimal",
    "decimal_to_american",
    "calculate_combined_odds",
    "format_american_odds",
    "calculate_parlay_payout",
]

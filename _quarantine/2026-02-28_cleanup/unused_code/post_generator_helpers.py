"""Helper functions for post generator - bet recommendations and formatting."""

from typing import Any, Dict, List

from src.betting import (
    breakeven_prob_from_american,
    prob_moneyline_win_from_mean_sd,
    prob_over_under_from_mean_sd,
    prob_spread_cover_from_mean_sd,
)


BET_THRESHOLDS = {
    "Total": {"min_edge": 2.0, "min_prob": 0.56, "edge_unit": "pts"},
    "Spread": {"min_edge": 1.5, "min_prob": 0.57, "edge_unit": "pts"},
    "Moneyline": {"min_edge": 0.03, "min_prob": 0.58, "edge_unit": "%"},
}


def _format_probability(p: float) -> str:
    """Format probability as percentage."""
    if p is None:
        return "N/A"
    return f"{p*100:.1f}%"


def _confidence_tier(probability: float) -> str:
    """Map hit probability to confidence tier."""
    p = float(probability)
    if p >= 0.65:
        return "A+"
    if p >= 0.62:
        return "A"
    if p >= 0.59:
        return "B+"
    if p >= 0.56:
        return "B"
    return "No bet"


def _passes_thresholds(bet_type: str, edge_value: float, hit_probability: float) -> bool:
    cfg = BET_THRESHOLDS[bet_type]
    return float(edge_value) >= float(cfg["min_edge"]) and float(hit_probability) >= float(cfg["min_prob"])


def _generate_best_bets(
    prediction: Dict[str, Any],
    prediction_type: str = "halftime",  # or "q3"
    max_bets: int = 3,
) -> List[Dict[str, Any]]:
    """Generate top bet recommendations from prediction.

    Edge remains the primary sort key and hit probability is the secondary key.
    Bets are only recommended when BOTH edge and probability thresholds pass.
    """
    import logging

    logger = logging.getLogger(__name__)
    bets: List[Dict[str, Any]] = []

    total = prediction.get("total", 0)
    margin = prediction.get("margin", 0)
    total_sd = float(prediction.get("total_sd", 8.0) or 8.0)
    margin_sd = float(prediction.get("margin_sd", 6.0) or 6.0)
    home_team = prediction.get("home_name", "Home")
    away_team = prediction.get("away_name", "Away")

    odds_total_line = prediction.get("odds_total_line")
    odds_total_over = prediction.get("odds_total_over")
    odds_total_under = prediction.get("odds_total_under")
    odds_spread_home_line = prediction.get("odds_spread_home_line")
    odds_spread_home_odds = prediction.get("odds_spread_home")
    odds_spread_away_odds = prediction.get("odds_spread_away")
    odds_home_ml = prediction.get("odds_home_ml")
    odds_away_ml = prediction.get("odds_away_ml")

    logger.info("_generate_best_bets: prediction_type=%s", prediction_type)

    if odds_total_line is None and odds_spread_home_line is None and (odds_home_ml is None or odds_away_ml is None):
        logger.warning("  ⚠️ No odds available in prediction - cannot generate bets")
        return []

    if not isinstance(total, (int, float)) or not isinstance(margin, (int, float)):
        logger.warning("  ⚠️ Invalid prediction payload, missing numeric total/margin")
        return []

    game_label = f"{away_team} vs {home_team}"

    # Totals
    if odds_total_line is not None:
        line = float(odds_total_line)
        p_over = prob_over_under_from_mean_sd(float(total), total_sd, line)
        p_under = 1.0 - p_over

        if odds_total_over is not None:
            edge_over = float(total) - line
            if _passes_thresholds("Total", edge_over, p_over):
                bets.append(
                    {
                        "game": game_label,
                        "type": "Total",
                        "side": f"Over {line:.1f}",
                        "line": line,
                        "odds": int(odds_total_over),
                        "model_prediction": float(total),
                        "hit_probability": p_over,
                        "probability": p_over,
                        "edge_value": edge_over,
                        "edge": edge_over,
                        "edge_unit": "pts",
                        "confidence_tier": _confidence_tier(p_over),
                        "variance": total_sd,
                    }
                )

        if odds_total_under is not None:
            edge_under = line - float(total)
            if _passes_thresholds("Total", edge_under, p_under):
                bets.append(
                    {
                        "game": game_label,
                        "type": "Total",
                        "side": f"Under {line:.1f}",
                        "line": line,
                        "odds": int(odds_total_under),
                        "model_prediction": float(total),
                        "hit_probability": p_under,
                        "probability": p_under,
                        "edge_value": edge_under,
                        "edge": edge_under,
                        "edge_unit": "pts",
                        "confidence_tier": _confidence_tier(p_under),
                        "variance": total_sd,
                    }
                )

    # Spreads
    if odds_spread_home_line is not None:
        spread = float(odds_spread_home_line)
        p_home_cover = prob_spread_cover_from_mean_sd(float(margin), margin_sd, spread)
        p_away_cover = 1.0 - p_home_cover
        edge_home = float(margin) + spread
        edge_away = -edge_home

        if odds_spread_home_odds is not None and _passes_thresholds("Spread", edge_home, p_home_cover):
            bets.append(
                {
                    "game": game_label,
                    "type": "Spread",
                    "side": f"{home_team} {spread:+.1f}",
                    "line": spread,
                    "odds": int(odds_spread_home_odds),
                    "model_prediction": float(margin),
                    "hit_probability": p_home_cover,
                    "probability": p_home_cover,
                    "edge_value": edge_home,
                    "edge": edge_home,
                    "edge_unit": "pts",
                    "confidence_tier": _confidence_tier(p_home_cover),
                    "variance": margin_sd,
                }
            )

        away_line = -spread
        if odds_spread_away_odds is not None and _passes_thresholds("Spread", edge_away, p_away_cover):
            bets.append(
                {
                    "game": game_label,
                    "type": "Spread",
                    "side": f"{away_team} {away_line:+.1f}",
                    "line": away_line,
                    "odds": int(odds_spread_away_odds),
                    "model_prediction": float(-margin),
                    "hit_probability": p_away_cover,
                    "probability": p_away_cover,
                    "edge_value": edge_away,
                    "edge": edge_away,
                    "edge_unit": "pts",
                    "confidence_tier": _confidence_tier(p_away_cover),
                    "variance": margin_sd,
                }
            )

    # Moneyline
    if odds_home_ml is not None and odds_away_ml is not None:
        model_home_win_prob = prediction.get("home_win_prob")
        if isinstance(model_home_win_prob, (int, float)):
            p_home_win = max(0.0, min(1.0, float(model_home_win_prob)))
        else:
            p_home_win = prob_moneyline_win_from_mean_sd(float(margin), margin_sd)

        p_away_win = 1.0 - p_home_win
        home_be = breakeven_prob_from_american(int(odds_home_ml))
        away_be = breakeven_prob_from_american(int(odds_away_ml))
        edge_home_ml = p_home_win - home_be
        edge_away_ml = p_away_win - away_be

        if _passes_thresholds("Moneyline", edge_home_ml, p_home_win):
            bets.append(
                {
                    "game": game_label,
                    "type": "Moneyline",
                    "side": f"{home_team} ML",
                    "line": None,
                    "odds": int(odds_home_ml),
                    "model_prediction": p_home_win,
                    "hit_probability": p_home_win,
                    "probability": p_home_win,
                    "edge_value": edge_home_ml,
                    "edge": edge_home_ml,
                    "edge_unit": "%",
                    "confidence_tier": _confidence_tier(p_home_win),
                    "variance": margin_sd,
                }
            )

        if _passes_thresholds("Moneyline", edge_away_ml, p_away_win):
            bets.append(
                {
                    "game": game_label,
                    "type": "Moneyline",
                    "side": f"{away_team} ML",
                    "line": None,
                    "odds": int(odds_away_ml),
                    "model_prediction": p_away_win,
                    "hit_probability": p_away_win,
                    "probability": p_away_win,
                    "edge_value": edge_away_ml,
                    "edge": edge_away_ml,
                    "edge_unit": "%",
                    "confidence_tier": _confidence_tier(p_away_win),
                    "variance": margin_sd,
                }
            )

    bets.sort(
        key=lambda b: (
            float(b["edge_value"]),
            float(b["hit_probability"]),
            -float(b.get("variance", 0.0)),
        ),
        reverse=True,
    )

    final_bets = bets[: max(0, int(max_bets))]
    logger.info("  Generated %s bets (from %s total candidates)", len(final_bets), len(bets))
    return final_bets

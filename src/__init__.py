"""
PerryPicks v4 - NBA Game Prediction System

A statistically rigorous NBA prediction system featuring:
- REPTAR: Halftime prediction model (75% win accuracy, Brier 0.19)
- Pregame model with 72 temporal features
- Q3 in-game prediction model
- NBA CDN schedule integration

Usage:
    from src.reptar import load_reptar_model, calculate_reptar_win_probability
    from src.schedule import fetch_games_around_date
    from src.models.pregame import PregameModel
"""

__version__ = "4.0.0"

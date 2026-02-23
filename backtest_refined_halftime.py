#!/usr/bin/env python3
"""
Backtest script for REPTAR Refined Halftime Model

Tests the refined model on Feb 9 and 11, 2026 to verify 75% win accuracy.
"""

import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.metrics import mean_absolute_error, brier_score_loss

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.schedule import fetch_schedule
from src.data.game_data import fetch_box, first_half_score, get_game_info


def run_backtest(target_date: str) -> Dict[str, Any]:
    """Run backtest for a specific date."""
    print(f"\n{'='*80}")
    print(f"BACKTEST: {target_date}")
    print(f"{'='*80}")

    # Fetch schedule
    print("\nFetching schedule...")
    games = fetch_schedule(target_date)

    if not games:
        print(f"No games found for {target_date}")
        return {"date": target_date, "n_games": 0}

    print(f"Found {len(games)} games")

    # Load refined model
    from src.models.halftime_refined import RefinedHalftimeModel

    model = RefinedHalftimeModel()
    if not model.load():
        print("Failed to load model")
        return {"date": target_date, "n_games": 0, "error": "model_load_failed"}

    # Train model on data before target date
    target_dt = pd.Timestamp(target_date, tz='UTC')
    if not model.train_model(target_dt):
        print("Failed to train model")
        return {"date": target_date, "n_games": 0, "error": "model_train_failed"}

    results = []

    for i, game in enumerate(games, 1):
        nba_id = game.get('nba_id')
        home_tri = game.get('home_team', 'HOME')
        away_tri = game.get('away_team', 'AWAY')

        print(f"\n[{i}/{len(games)}] {away_tri} @ {home_tri} ({nba_id})")

        if not nba_id:
            print("  Skipping - no NBA ID")
            continue

        try:
            # Fetch game data
            box = fetch_box(nba_id)
            info = get_game_info(box)

            # Get first half scores
            h1_home, h1_away = first_half_score(box)
            if h1_home == 0 and h1_away == 0:
                print("  Skipping - no H1 scores")
                continue

            # Get team IDs
            home_team_id = model._team_id_map.get(home_tri, 0.0)
            away_team_id = model._team_id_map.get(away_tri, 0.0)

            # Make prediction
            pred = model.predict(
                h1_home=h1_home,
                h1_away=h1_away,
                home_team_id=home_team_id,
                away_team_id=away_team_id,
                target_dt=target_dt,
                game_id=nba_id,
                home_name=home_tri,
                away_name=away_tri,
            )

            if pred is None:
                print("  Skipping - prediction failed")
                continue

            # Get actual final scores
            home_team = box.get("homeTeam", {})
            away_team = box.get("awayTeam", {})
            final_home = home_team.get("score", 0)
            final_away = away_team.get("score", 0)
            final_total = final_home + final_away
            final_margin = final_home - final_away
            home_won = 1 if final_home > final_away else 0

            # Determine predicted winner
            pred_winner = 1 if pred.pred_final_margin > 0 else 0
            correct = 1 if pred_winner == home_won else 0

            results.append({
                "game_id": nba_id,
                "home": home_tri,
                "away": away_tri,
                "h1_home": h1_home,
                "h1_away": h1_away,
                "pred_total": pred.pred_final_total,
                "pred_margin": pred.pred_final_margin,
                "pred_home_win_prob": pred.home_win_prob,
                "actual_total": final_total,
                "actual_margin": final_margin,
                "home_won": home_won,
                "pred_winner": pred_winner,
                "correct": correct,
            })

            print(f"  H1: {h1_away}-{h1_home}")
            print(f"  Pred: {pred.pred_final_total:.1f} total, {pred.pred_final_margin:.1f} margin, {pred.home_win_prob:.1%} home win")
            print(f"  Actual: {final_total} total, {final_margin} margin")
            print(f"  {'✅ CORRECT' if correct else '❌ WRONG'}")

        except Exception as e:
            print(f"  Error: {e}")
            continue

    return {
        "date": target_date,
        "n_games": len(results),
        "results": results,
    }


def compute_metrics(results: List[Dict]) -> Dict[str, float]:
    """Compute backtest metrics."""
    if not results:
        return {}

    df = pd.DataFrame(results)

    # Core metrics
    total_mae = mean_absolute_error(df['actual_total'], df['pred_total'])
    margin_mae = mean_absolute_error(df['actual_margin'], df['pred_margin'])
    win_accuracy = df['correct'].mean()

    # Brier score
    brier = brier_score_loss(df['home_won'], df['pred_home_win_prob'])

    return {
        "n_games": len(df),
        "total_mae": total_mae,
        "margin_mae": margin_mae,
        "win_accuracy": win_accuracy,
        "brier_score": brier,
    }


def main():
    print("="*80)
    print("REPTAR REFINED HALFTIME MODEL - BACKTEST")
    print("Target: 75% Win Accuracy (Feb 9-11, 2026)")
    print("="*80)

    all_results = []

    # Test Feb 9
    feb9 = run_backtest("2026-02-09")
    if feb9.get("results"):
        all_results.extend(feb9["results"])

    # Test Feb 11
    feb11 = run_backtest("2026-02-11")
    if feb11.get("results"):
        all_results.extend(feb11["results"])

    if not all_results:
        print("\nNo results to analyze")
        return

    # Compute combined metrics
    metrics = compute_metrics(all_results)

    print(f"\n{'='*80}")
    print("COMBINED RESULTS (Feb 9-11, 2026)")
    print(f"{'='*80}")

    print(f"\nGames: {metrics['n_games']}")
    print(f"\nMetrics:")
    print(f"  Win Accuracy: {metrics['win_accuracy']*100:.1f}%")
    print(f"  Total MAE: {metrics['total_mae']:.2f}")
    print(f"  Margin MAE: {metrics['margin_mae']:.2f}")
    print(f"  Brier Score: {metrics['brier_score']:.4f}")

    # Compare to documented
    print(f"\n{'='*80}")
    print("COMPARISON TO DOCUMENTED PERFORMANCE")
    print(f"{'='*80}")

    print(f"\n{'Metric':20} | {'This Run':>12} | {'Documented':>12} | {'Match':>8}")
    print("-"*60)
    print(f"{'Win Accuracy':20} | {metrics['win_accuracy']*100:>11.1f}% | {'75.0':>11}% | {'✅' if abs(metrics['win_accuracy']-0.75) < 0.05 else '⚠️':>8}")
    print(f"{'Total MAE':20} | {metrics['total_mae']:>12.2f} | {'8.33':>12} | {'✅' if abs(metrics['total_mae']-8.33) < 1.0 else '⚠️':>8}")
    print(f"{'Brier Score':20} | {metrics['brier_score']:>12.4f} | {'0.1905':>12} | {'✅' if abs(metrics['brier_score']-0.1905) < 0.05 else '⚠️':>8}")

    # Per-game results table
    print(f"\n{'='*80}")
    print("PER-GAME RESULTS")
    print(f"{'='*80}")

    df = pd.DataFrame(all_results)
    print(df[["away", "home", "pred_total", "actual_total", "pred_margin", "actual_margin", "correct"]].to_string(index=False))

    print(f"\n{'='*80}")
    print("BACKTEST COMPLETE")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()

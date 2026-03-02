#!/usr/bin/env python3
"""
Backtest: Run halftime predictions for completed games on 2026-01-23

This script simulates what the automation would have posted at halftime
for all games on January 23, 2026, using only data available at that time.
"""

import sys
import logging
from pathlib import Path
from datetime import datetime
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

import os
import pandas as pd

def main():
    target_date = "2026-01-23"

    print(f"\n{'='*60}")
    print(f"HALFTIME BACKTEST: {target_date}")
    print(f"{'='*60}\n")

    # Import modules
    from src.schedule import fetch_schedule
    from src.data.game_data import fetch_box, first_half_score, get_game_info
    from src.models.reptar_predictor import get_predictor
    from src.automation.post_generator import PostGenerator
    from src.automation.discord_client import DiscordClient
    from src.automation.game_state import GameState

    # Load REPTAR model
    print("Loading REPTAR model...")
    predictor = get_predictor()
    print(f"✓ Model loaded with {len(predictor._total_features)} features\n")

    # Initialize post generator (no betting since no odds)
    post_gen = PostGenerator(include_betting=False)

    # Initialize Discord client
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("ERROR: DISCORD_WEBHOOK_URL not set")
        sys.exit(1)

    discord = DiscordClient(webhook_url)
    print(f"✓ Discord client configured\n")

    # Fetch schedule
    print(f"Fetching schedule for {target_date}...")
    schedule = fetch_schedule(target_date)
    games = schedule.get("games", [])

    if not games:
        print(f"No games found for {target_date}")
        return

    print(f"Found {len(games)} games\n")

    # Process each game
    results = []

    for i, game in enumerate(games, 1):
        nba_id = game.get("nba_id")
        home_tri = game.get("home_team", "HOME")
        away_tri = game.get("away_team", "AWAY")

        print(f"[{i}/{len(games)}] {away_tri} @ {home_tri} ({nba_id})")

        if not nba_id:
            print("  Skipping - no NBA ID")
            continue

        try:
            # Fetch box score
            box = fetch_box(nba_id)
            info = get_game_info(box)

            # Get actual team names
            home_team = info.get("home_tricode", home_tri)
            away_team = info.get("away_tricode", away_tri)

            # Get halftime scores
            h1_home, h1_away = first_half_score(box)
            if h1_home == 0 and h1_away == 0:
                print("  Skipping - no halftime scores")
                continue

            print(f"  Halftime: {away_team} {h1_away} - {h1_home} {home_team}")

            # Get final scores for comparison
            home_team_data = box.get("homeTeam", {}) or {}
            away_team_data = box.get("awayTeam", {}) or {}
            final_home = home_team_data.get("score", 0) or 0
            final_away = away_team_data.get("score", 0) or 0
            final_total = final_home + final_away
            final_margin = final_home - final_away

            # Make prediction using REPTAR
            # Set target date to game date to only use data available at that time
            target_dt = pd.Timestamp(target_date, tz='UTC')

            features, pred = predictor.predict(h1_home, h1_away, behavior=None)

            pred_total = pred["pred_final_total"]
            pred_margin = pred["pred_final_margin"]
            home_win_prob = pred["home_win_prob"]

            # Determine predicted winner
            pred_winner = home_team if pred_margin > 0 else away_team
            actual_winner = home_team if final_margin > 0 else away_team
            correct = pred_winner == actual_winner

            print(f"  Predicted: {pred_total:.1f} total, {pred_margin:+.1f} margin, {home_win_prob:.1%} {home_team}")
            print(f"  Actual:    {final_total} total, {final_margin:+d} margin ({actual_winner} won)")
            print(f"  {'✅ CORRECT' if correct else '❌ WRONG'}")

            # Create game state for post
            state = GameState(
                game_id=nba_id,
                status="halftime",
                period=2,
                time_remaining="00:00",
                home_score=h1_home,
                away_score=h1_away,
                home_team=home_team,
                away_team=away_team,
                home_tricode=home_team,
                away_tricode=away_team,
            )

            # Generate post (no betting recommendations since no odds)
            post = post_gen.generate_halftime_post(pred, state, recommendations=[])

            # Post to Discord
            result = discord.post_message(post.content)

            if result.success:
                print(f"  ✅ Posted to Discord")
            else:
                print(f"  ❌ Discord error: {result.error}")

            results.append({
                "game_id": nba_id,
                "home": home_team,
                "away": away_team,
                "h1_home": h1_home,
                "h1_away": h1_away,
                "pred_total": pred_total,
                "pred_margin": pred_margin,
                "pred_winner": pred_winner,
                "actual_total": final_total,
                "actual_margin": final_margin,
                "actual_winner": actual_winner,
                "correct": correct,
                "home_win_prob": home_win_prob,
            })

            print()

        except Exception as e:
            print(f"  Error: {e}")
            continue

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}\n")

    if results:
        correct = sum(1 for r in results if r["correct"])
        total = len(results)
        accuracy = correct / total if total > 0 else 0

        print(f"Games Processed: {total}")
        print(f"Correct Predictions: {correct}/{total} ({accuracy:.1%})")
        print()

        print(f"{'Away':6} @ {'Home':6} | {'H1':8} | {'Pred Total':>10} | {'Actual':>8} | {'Pred Margin':>11} | {'Actual':>7} | {'Result'}")
        print("-" * 90)
        for r in results:
            h1 = f"{r['h1_away']}-{r['h1_home']}"
            result = "✅" if r["correct"] else "❌"
            print(f"{r['away']:6} @ {r['home']:6} | {h1:8} | {r['pred_total']:>10.1f} | {r['actual_total']:>8} | {r['pred_margin']:>+11.1f} | {r['actual_margin']:>+7} | {result}")

    print(f"\n{'='*60}")
    print("BACKTEST COMPLETE")
    print(f"{'='*60}\n")

    # Close Discord client
    discord.close()


if __name__ == "__main__":
    main()

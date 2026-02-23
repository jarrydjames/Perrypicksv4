#!/usr/bin/env python3
"""
Run PerryPicks Automation Service

Integrates REPTAR CatBoost model with game monitoring and Discord posting.

IMPORTANT: This script requires the virtual environment with CatBoost.
Run with: source .venv/bin/activate && python run_automation.py

Usage:
    # Activate venv and run
    source .venv/bin/activate
    python run_automation.py --webhook-url "https://discord.com/api/webhooks/..."

    # Or set environment variable
    export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
    source .venv/bin/activate && python run_automation.py
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Reduce noise from third-party libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


def main():
    parser = argparse.ArgumentParser(
        description="Run PerryPicks Automation Service with REPTAR Model"
    )
    parser.add_argument(
        "--webhook-url",
        type=str,
        default=os.environ.get("DISCORD_WEBHOOK_URL"),
        help="Discord webhook URL (or set DISCORD_WEBHOOK_URL env var)",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=int(os.environ.get("POLL_INTERVAL", "30")),
        help="Polling interval in seconds (default: 30)",
    )
    parser.add_argument(
        "--no-betting",
        action="store_true",
        help="Disable betting recommendations in posts",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    setup_logging(args.verbose)

    if not args.webhook_url:
        print("Error: Discord webhook URL required")
        print("Set DISCORD_WEBHOOK_URL environment variable or use --webhook-url")
        sys.exit(1)

    # Import here after logging is set up
    from src.automation import AutomationService
    from src.automation.triggers import TriggerType
    from src.automation.game_state import GameState
    from src.models.reptar_predictor import get_predictor

    # Load REPTAR model
    logger = logging.getLogger(__name__)
    logger.info("Loading REPTAR CatBoost model...")

    try:
        predictor = get_predictor()
        logger.info("REPTAR model loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load REPTAR model: {e}")
        sys.exit(1)

    # Create prediction callback that uses REPTAR
    def prediction_callback(game_id: str, trigger_type: TriggerType, state: GameState) -> dict:
        """Generate prediction using REPTAR model."""
        try:
            pred = predictor.predict_from_game_id(game_id)
            if pred is None:
                logger.error(f"REPTAR prediction returned None for {game_id}")
                return None

            logger.info(
                f"REPTAR prediction for {pred.away_team} @ {pred.home_team}: "
                f"Final {pred.pred_final_total:.1f} total, {pred.pred_final_margin:+.1f} margin, "
                f"{pred.home_win_prob:.1%} home win"
            )

            return predictor.to_dict(pred)

        except Exception as e:
            logger.error(f"REPTAR prediction failed for {game_id}: {e}")
            return None

    # Create and start service
    service = AutomationService(
        discord_webhook_url=args.webhook_url,
        prediction_callback=prediction_callback,
        poll_interval=args.poll_interval,
        include_betting=not args.no_betting,
    )

    print(f"\n{'='*60}")
    print("PerryPicks Automation Service")
    print("Powered by REPTAR CatBoost Model")
    print(f"{'='*60}")
    print(f"Poll Interval: {args.poll_interval}s")
    print(f"Betting: {'Disabled' if args.no_betting else 'Enabled'}")
    print(f"Model: CatBoost (MAE Total: 7.96, MAE Margin: 3.85)")
    print(f"{'='*60}\n")

    try:
        service.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
        service.stop()


if __name__ == "__main__":
    main()

#!/bin/bash
# Start PerryPicks Automation with REPTAR CatBoost Model
#
# Usage:
#   ./start_automation.sh                    # Uses .env file
#   ./start_automation.sh --webhook-url URL  # Override webhook

set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Load environment variables from .env if it exists
if [ -f ".env" ]; then
    echo "Loading configuration from .env..."
    source .env
    export DISCORD_WEBHOOK_URL ODDS_API_KEY POLL_INTERVAL
fi

# Check if venv exists
if [ ! -d ".venv" ]; then
    echo "Error: Virtual environment not found."
    echo "Please run: python3.12 -m venv .venv && source .venv/bin/activate && pip install catboost pandas numpy scipy requests joblib"
    exit 1
fi

# Activate venv and run
source .venv/bin/activate
python run_automation.py "$@"

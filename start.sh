#!/bin/bash
# PerryPicks Startup Script
# Usage: ./start.sh [--with-frontend] [--no-discord]

cd "$(dirname "$0")"

# Activate virtual environment
source .venv/bin/activate

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Start PerryPicks
python start.py "$@"

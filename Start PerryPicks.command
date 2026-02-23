#!/bin/bash
#
# PerryPicks Launcher - Double-click to start
# This script starts the full PerryPicks automation suite
#

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Configuration
LOG_FILE="/tmp/perrypicks.log"
PID_FILE="$SCRIPT_DIR/.perrypicks.pid"

echo "=============================================="
echo "  PerryPicks - NBA Prediction System"
echo "=============================================="
echo ""

# Check if already running
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "ERROR: PerryPicks is already running (PID $OLD_PID)"
        echo ""
        echo "To stop it, run: kill $OLD_PID"
        echo "Or delete the PID file: rm '$PID_FILE'"
        echo ""
        read -p "Press Enter to close..."
        exit 1
    else
        echo "Removing stale PID file..."
        rm "$PID_FILE"
    fi
fi

# Find Python
if [ -f "$SCRIPT_DIR/.venv/bin/python3" ]; then
    PYTHON="$SCRIPT_DIR/.venv/bin/python3"
    echo "Using venv Python: $PYTHON"
elif command -v python3 &> /dev/null; then
    PYTHON="python3"
    echo "Using system Python: $PYTHON"
else
    echo "ERROR: Python3 not found"
    read -p "Press Enter to close..."
    exit 1
fi

# Check for required files
if [ ! -f "$SCRIPT_DIR/start.py" ]; then
    echo "ERROR: start.py not found in $SCRIPT_DIR"
    read -p "Press Enter to close..."
    exit 1
fi

if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "WARNING: .env file not found - Discord posting may be disabled"
fi

# Create logs directory if needed
mkdir -p "$SCRIPT_DIR/logs"

echo ""
echo "Starting PerryPicks..."
echo "Log file: $LOG_FILE"
echo ""
echo "Press Ctrl+C to stop"
echo "=============================================="
echo ""

# Run PerryPicks
"$PYTHON" "$SCRIPT_DIR/start.py" 2>&1 | tee "$LOG_FILE"

# If we get here, the process ended
echo ""
echo "PerryPicks has stopped."
read -p "Press Enter to close..."

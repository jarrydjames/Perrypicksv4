#!/bin/bash
#
# PerryPicks Stopper - Double-click to stop
#

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PID_FILE="$SCRIPT_DIR/.perrypicks.pid"

echo "=============================================="
echo "  Stopping PerryPicks"
echo "=============================================="
echo ""

# Check PID file
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "Stopping PerryPicks (PID $PID)..."
        kill "$PID" 2>/dev/null
        
        # Wait for process to stop
        sleep 2
        
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "Process still running, forcing stop..."
            kill -9 "$PID" 2>/dev/null
            sleep 1
        fi
        
        # Clean up PID file
        rm -f "$PID_FILE"
        echo "PerryPicks stopped."
    else
        echo "Process $PID is not running."
        echo "Cleaning up stale PID file..."
        rm -f "$PID_FILE"
    fi
else
    echo "No PID file found."
    
    # Try to find and kill any start.py processes
    PIDS=$(pgrep -f "start.py" 2>/dev/null)
    if [ -n "$PIDS" ]; then
        echo "Found running PerryPicks processes:"
        echo "$PIDS"
        echo ""
        read -p "Kill these processes? (y/n): " CONFIRM
        if [ "$CONFIRM" = "y" ] || [ "$CONFIRM" = "Y" ]; then
            echo "$PIDS" | xargs kill 2>/dev/null
            echo "Processes killed."
        fi
    else
        echo "No PerryPicks processes found."
    fi
fi

echo ""
read -p "Press Enter to close..."

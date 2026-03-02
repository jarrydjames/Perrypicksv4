#!/bin/bash
#
# Start Watchdog + Automation
#
# This script starts the health watchdog and then the main automation.
# Both processes run independently.
#
# Usage:
#   ./start_with_watchdog.sh
#   ./start_with_watchdog.sh [--check-interval 60]
#

set -e

cd "$(dirname "$0")"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║     PerryPicks - Starting with Health Watchdog                  ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Parse arguments
CHECK_INTERVAL="${CHECK_INTERVAL:-60}"

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --check-interval)
            CHECK_INTERVAL="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--check-interval SECONDS]"
            exit 1
            ;;
    esac
done

echo "⚙️  Configuration:"
echo "   Check interval: ${CHECK_INTERVAL}s"
echo ""

# Check if watchdog is already running
if [ -f .watchdog.pid ]; then
    WATCHDOG_PID=$(cat .watchdog.pid)
    if ps -p $WATCHDOG_PID > /dev/null 2>&1; then
        echo "⚠️  Watchdog already running (PID: $WATCHDOG_PID)"
        echo "   Run: kill -15 $WATCHDOG_PID to stop it"
        echo ""
    else
        echo "🧹 Cleaning up stale watchdog PID file"
        rm .watchdog.pid
        echo ""
    fi
fi

# Check if automation is already running
if [ -f .perrypicks.pid ]; then
    AUTOMATION_PID=$(cat .perrypicks.pid)
    if ps -p $AUTOMATION_PID > /dev/null 2>&1; then
        echo "⚠️  Automation already running (PID: $AUTOMATION_PID)"
        echo "   Run: kill -15 $AUTOMATION_PID to stop it"
        echo ""
        read -p "Continue anyway? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Aborted."
            exit 1
        fi
    else
        echo "🧹 Cleaning up stale automation PID file"
        rm .perrypicks.pid
        echo ""
    fi
fi


# Check if MAXIMUS is already running
if [ -f .maximus.pid ]; then
    MAXIMUS_PID=$(cat .maximus.pid)
    if ps -p $MAXIMUS_PID > /dev/null 2>&1; then
        echo "⚠️  MAXIMUS already running (PID: $MAXIMUS_PID)"
        echo "   Run: kill -15 $MAXIMUS_PID to stop it"
        echo ""
        read -p "Continue anyway? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Aborted."
            exit 1
        fi
    else
        echo "🧹 Cleaning up stale MAXIMUS PID file"
        rm .maximus.pid
        echo ""
    fi
fi


# Check if Market Tracking is already running
if [ -f .market_tracking.pid ]; then
    MARKET_TRACK_PID=$(cat .market_tracking.pid)
    if ps -p $MARKET_TRACK_PID > /dev/null 2>&1; then
        echo "⚠️  Market Tracking already running (PID: $MARKET_TRACK_PID)"
        echo "   Run: kill -15 $MARKET_TRACK_PID to stop it"
        echo ""
        read -p "Continue anyway? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Aborted."
            exit 1
        fi
    else
        echo "🧹 Cleaning up stale Market Tracking PID file"
        rm .market_tracking.pid
        echo ""
    fi
fi

# Activate virtual environment
if [ -f .venv/bin/activate ]; then
    echo "🔧 Activating virtual environment..."
    source .venv/bin/activate
else
    echo "⚠️  Virtual environment not found. Using system Python."
    echo ""
fi

# Start automation FIRST (prevents watchdog from racing the PID file / health checks)
echo "🚀 Starting Automation..."
nohup .venv/bin/python start.py > perrypicks_automation.log 2>&1 &
AUTOMATION_PID=$!
echo "   PID: $AUTOMATION_PID"
echo "   Logs: perrypicks_automation.log"

# Wait for automation PID file
echo "⏳ Waiting for automation PID file..."
for i in {1..30}; do
    if [ -f .perrypicks.pid ]; then
        break
    fi
    sleep 1
done

if [ ! -f .perrypicks.pid ]; then
    echo "   ❌ Automation PID file not created"
    echo "   Check: tail -50 perrypicks_automation.log"
    exit 1
fi

AUTOMATION_PID=$(cat .perrypicks.pid)
if ! ps -p $AUTOMATION_PID > /dev/null 2>&1; then
    echo "   ❌ Automation failed to start"
    echo "   Check: tail -50 perrypicks_automation.log"
    exit 1
fi

echo "   ✅ Automation started successfully (PID: $AUTOMATION_PID)"

echo "⏳ Waiting for backend health (http://localhost:8000/api/health)..."
BACKEND_OK=0
for i in {1..180}; do
    if curl -fsS "http://localhost:8000/api/health" > /dev/null 2>&1; then
        echo "   ✅ Backend health check OK"
        BACKEND_OK=1
        break
    fi
    sleep 1
done

if [ $BACKEND_OK -ne 1 ]; then
    echo "   ⚠️  Backend health not ready yet (continuing anyway)"
    echo "   (Automation may still be booting; check perrypicks_automation.log)"
fi


# Start MAXIMUS sidecar (pregame + daily summary)
echo "🤖 Starting MAXIMUS (pregame + daily summary)..."
nohup .venv/bin/python run_maximus_pregame.py > maximus.log 2>&1 &
MAXIMUS_PID=$!
echo $MAXIMUS_PID > .maximus.pid

echo "   PID: $MAXIMUS_PID"
echo "   Logs: maximus.log"

# Wait briefly and verify
sleep 2
if ps -p $MAXIMUS_PID > /dev/null 2>&1; then
    echo "   ✅ MAXIMUS started successfully"
else
    echo "   ❌ MAXIMUS failed to start"
    echo "   Check: tail -50 maximus.log"
    exit 1
fi

echo ""

echo ""


# Start Market Tracking sidecar (market-implied likelihood)
echo "📈 Starting Market Tracking (book-implied)..."
nohup .venv/bin/python run_market_tracking.py > market_tracking.log 2>&1 &
MARKET_TRACK_PID=$!
echo $MARKET_TRACK_PID > .market_tracking.pid

echo "   PID: $MARKET_TRACK_PID"
echo "   Logs: market_tracking.log"

sleep 2
if ps -p $MARKET_TRACK_PID > /dev/null 2>&1; then
    echo "   ✅ Market Tracking started successfully"
else
    echo "   ❌ Market Tracking failed to start"
    echo "   Check: tail -50 market_tracking.log"
    exit 1
fi

echo ""

# Start watchdog AFTER automation is alive
echo "🐕 Starting Health Watchdog..."
nohup .venv/bin/python watchdog.py --check-interval $CHECK_INTERVAL > watchdog.log 2>&1 &
WATCHDOG_PID=$!
echo "   PID: $WATCHDOG_PID"
echo "   Logs: watchdog.log"

# Wait for watchdog to start
sleep 3

# Verify watchdog is running
if [ -f .watchdog.pid ]; then
    WATCHDOG_PID=$(cat .watchdog.pid)
    if ps -p $WATCHDOG_PID > /dev/null 2>&1; then
        echo "   ✅ Watchdog started successfully"
    else
        echo "   ❌ Watchdog failed to start"
        echo "   Check: tail -50 watchdog.log"
        exit 1
    fi
else
    echo "   ❌ Watchdog PID file not created"
    echo "   Check: tail -50 watchdog.log"
    exit 1
fi

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║     🎉 Both Systems Running Successfully!                       ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "📋 Status Summary:"
echo "   Watchdog PID:    $WATCHDOG_PID"
echo "   MAXIMUS PID:     $MAXIMUS_PID"
echo "   MarketTrack PID: $MARKET_TRACK_PID"
echo "   Automation PID:   $AUTOMATION_PID"
echo "   Check interval:   ${CHECK_INTERVAL}s"
echo ""
echo "📝 Logs:"
echo "   Watchdog:   tail -f watchdog.log"
echo "   MAXIMUS:    tail -f maximus.log"
echo "   MarketTrack: tail -f market_tracking.log"
echo "   Automation: tail -f perrypicks_automation.log"
echo ""
echo "🛑 To stop both systems:"
echo "   ./stop_with_watchdog.sh"
echo "   Or individually:"
echo "     kill -15 $WATCHDOG_PID   # Stop watchdog"
echo "     kill -15 $MAXIMUS_PID    # Stop MAXIMUS"
echo "     kill -15 $MARKET_TRACK_PID # Stop Market Tracking"
echo "     kill -15 $AUTOMATION_PID  # Stop automation"
echo ""
echo "🚀 PerryPicks is now running with health monitoring!"
echo ""

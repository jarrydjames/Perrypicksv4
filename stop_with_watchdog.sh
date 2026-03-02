#!/bin/bash
#
# Stop Watchdog + Automation
#
# This script stops both the health watchdog and the main automation.
#
# Usage:
#   ./stop_with_watchdog.sh
#

set -e

cd "$(dirname "$0")"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║     PerryPicks - Stopping Watchdog + Automation               ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

STOPPED=0

# Stop watchdog
if [ -f .watchdog.pid ]; then
    WATCHDOG_PID=$(cat .watchdog.pid)
    if ps -p $WATCHDOG_PID > /dev/null 2>&1; then
        echo "🐕 Stopping Health Watchdog (PID: $WATCHDOG_PID)..."
        kill -15 $WATCHDOG_PID
        sleep 2
        
        # Check if still running
        if ps -p $WATCHDOG_PID > /dev/null 2>&1; then
            echo "   Force killing..."
            kill -9 $WATCHDOG_PID
            sleep 1
        fi
        
        # Remove PID file
        rm -f .watchdog.pid
        echo "   ✅ Watchdog stopped"
        echo ""
        STOPPED=$((STOPPED + 1))
    else
        echo "⚠️  Watchdog not running (stale PID file)"
        rm -f .watchdog.pid
        echo "   ✅ Removed stale PID file"
        echo ""
    fi
else
    echo "⚠️  Watchdog not running (no PID file)"
    echo ""
fi


# Stop MAXIMUS sidecar
if [ -f .maximus.pid ]; then
    MAXIMUS_PID=$(cat .maximus.pid)
    if ps -p $MAXIMUS_PID > /dev/null 2>&1; then
        echo "🤖 Stopping MAXIMUS (PID: $MAXIMUS_PID)..."
        kill -15 $MAXIMUS_PID
        sleep 2

        if ps -p $MAXIMUS_PID > /dev/null 2>&1; then
            echo "   Force killing..."
            kill -9 $MAXIMUS_PID
            sleep 1
        fi

        rm -f .maximus.pid
        echo "   ✅ MAXIMUS stopped"
        echo ""
        STOPPED=$((STOPPED + 1))
    else
        echo "⚠️  MAXIMUS not running (stale PID file)"
        rm -f .maximus.pid
        echo "   ✅ Removed stale PID file"
        echo ""
    fi
else
    echo "⚠️  MAXIMUS not running (no PID file)"
    echo ""
fi


# Stop Market Tracking sidecar
if [ -f .market_tracking.pid ]; then
    MARKET_TRACK_PID=$(cat .market_tracking.pid)
    if ps -p $MARKET_TRACK_PID > /dev/null 2>&1; then
        echo "📈 Stopping Market Tracking (PID: $MARKET_TRACK_PID)..."
        kill -15 $MARKET_TRACK_PID
        sleep 2

        if ps -p $MARKET_TRACK_PID > /dev/null 2>&1; then
            echo "   Force killing..."
            kill -9 $MARKET_TRACK_PID
            sleep 1
        fi

        rm -f .market_tracking.pid
        echo "   ✅ Market Tracking stopped"
        echo ""
        STOPPED=$((STOPPED + 1))
    else
        echo "⚠️  Market Tracking not running (stale PID file)"
        rm -f .market_tracking.pid
        echo "   ✅ Removed stale PID file"
        echo ""
    fi
else
    echo "⚠️  Market Tracking not running (no PID file)"
    echo ""
fi

# Stop automation
if [ -f .perrypicks.pid ]; then
    AUTOMATION_PID=$(cat .perrypicks.pid)
    if ps -p $AUTOMATION_PID > /dev/null 2>&1; then
        echo "🚀 Stopping Automation (PID: $AUTOMATION_PID)..."
        kill -15 $AUTOMATION_PID
        sleep 3
        
        # Check if still running
        if ps -p $AUTOMATION_PID > /dev/null 2>&1; then
            echo "   Force killing..."
            kill -9 $AUTOMATION_PID
            sleep 1
        fi
        
        # Remove PID file
        rm -f .perrypicks.pid
        echo "   ✅ Automation stopped"
        echo ""
        STOPPED=$((STOPPED + 1))
    else
        echo "⚠️  Automation not running (stale PID file)"
        rm -f .perrypicks.pid
        echo "   ✅ Removed stale PID file"
        echo ""
    fi
else
    echo "⚠️  Automation not running (no PID file)"
    echo ""
fi

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║     ✅ Stopped $STOPPED system(s)                                 ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

if [ $STOPPED -eq 0 ]; then
    echo "ℹ️  Nothing was running."
    echo ""
fi

echo "📝 Logs (for debugging):"
echo "   Watchdog:   tail -50 watchdog.log"
echo "   Automation: tail -50 perrypicks_automation.log"
echo "   MAXIMUS:    tail -50 maximus.log"
echo "   MarketTrack: tail -50 market_tracking.log"
echo ""

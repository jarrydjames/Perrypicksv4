#!/bin/bash
#
# PerryPicks Status Dashboard
# Quick diagnostic overview of all services
#

set -e
cd "$(dirname "$0")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              PerryPicks System Status                           ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Helper function to check process
check_process() {
    local name=$1
    local pidfile=$2
    local heartbeat=$3
    
    echo -e "${BLUE}━━━ $name ━━━${NC}"
    
    # Check PID file
    if [ ! -f "$pidfile" ]; then
        echo -e "  Status:  ${RED}STOPPED${NC} (no PID file)"
        echo ""
        return 1
    fi
    
    PID=$(cat "$pidfile")
    
    # Check if process is running
    if ! ps -p $PID > /dev/null 2>&1; then
        echo -e "  Status:  ${RED}STOPPED${NC} (PID $PID not running)"
        echo -e "  PID:     $PID (stale)"
        echo ""
        return 1
    fi
    
    # Process is alive - get stats
    CPU=$(ps -p $PID -o %cpu= | tr -d ' ')
    MEM=$(ps -p $PID -o rss= | awk '{printf "%.1f", $1/1024}')
    
    echo -e "  Status:  ${GREEN}RUNNING${NC}"
    echo -e "  PID:     $PID"
    echo -e "  CPU:     ${CPU}%"
    echo -e "  Memory:  ${MEM} MB"
    
    # Check heartbeat
    if [ -n "$heartbeat" ] && [ -f "$heartbeat" ]; then
        AGE=$(( $(date +%s) - $(stat -f "%m" "$heartbeat") ))
        if [ $AGE -gt 300 ]; then
            echo -e "  Heartbeat: ${RED}STALE${NC} (${AGE}s ago)"
        elif [ $AGE -gt 120 ]; then
            echo -e "  Heartbeat: ${YELLOW}OLD${NC} (${AGE}s ago)"
        else
            echo -e "  Heartbeat: ${GREEN}FRESH${NC} (${AGE}s ago)"
        fi
    elif [ -n "$heartbeat" ]; then
        echo -e "  Heartbeat: ${RED}MISSING${NC}"
    fi
    
    echo ""
    return 0
}

# Check each service
check_process "Automation" ".perrypicks.pid" ".perrypicks.heartbeat"
check_process "MAXIMUS" ".maximus.pid" ".maximus.heartbeat"
check_process "Market Tracking" ".market_tracking.pid" ".market_tracking.heartbeat"
check_process "Watchdog" ".watchdog.pid" ""

# Check backend API
echo -e "${BLUE}━━━ Backend API ━━━${NC}"
if curl -fsS "http://localhost:8000/api/health" > /dev/null 2>&1; then
    echo -e "  Status:  ${GREEN}HEALTHY${NC}"
    echo -e "  URL:     http://localhost:8000"
else
    echo -e "  Status:  ${RED}NOT RESPONDING${NC}"
fi
echo ""

# Check Odds API
echo -e "${BLUE}━━━ Odds API ━━━${NC}"
if curl -fsS "http://localhost:8890/v1/health" > /dev/null 2>&1; then
    echo -e "  Status:  ${GREEN}HEALTHY${NC}"
    echo -e "  URL:     http://localhost:8890"
else
    echo -e "  Status:  ${RED}NOT RESPONDING${NC}"
fi
echo ""

# Quick log tail
echo -e "${BLUE}━━━ Recent Activity ━━━${NC}"
echo ""
echo "Automation (last 5 lines):"
tail -5 perrypicks_automation.log 2>/dev/null | sed 's/^/  /' || echo "  No logs"
echo ""

echo "Market Tracking (last 5 lines):"
tail -5 market_tracking.log 2>/dev/null | sed 's/^/  /' || echo "  No logs"
echo ""

echo "Watchdog (last 5 lines):"
tail -5 watchdog.log 2>/dev/null | sed 's/^/  /' || echo "  No logs"
echo ""

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Commands:                                                      ║"
echo "║  ./start_with_watchdog.sh   - Start all services              ║"
echo "║  ./stop_with_watchdog.sh    - Stop all services               ║"
echo "║  tail -f watchdog.log       - Watch watchdog logs             ║"
echo "║  tail -f market_tracking.log - Watch market tracking          ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# PerryPicks Reliability Improvements

## Overview
Multi-day reliability upgrades completed to ensure the system can run continuously without manual intervention.

## Improvements Implemented

### 1. Discord Rate Limit Protection
- **File**: `run_market_tracking.py`
- **Change**: Added `MARKET_TRACK_MAX_NEW_POSTS_PER_CYCLE` (default: 3)
- **Why**: Prevents Discord 429 rate limits that can freeze the market tracking sidecar for 20+ minutes
- **Impact**: Caps new tracker posts per 30-second cycle; edits are unlimited

### 2. Heartbeat Monitoring (Stuck Process Detection)
- **Files**: `run_market_tracking.py`, `watchdog.py`
- **Change**: All long-running services now write heartbeat files every cycle
  - `.perrypicks.heartbeat` (automation)
  - `.maximus.heartbeat` (maximus)
  - `.market_tracking.heartbeat` (market tracking)
- **Watchdog**: Checks heartbeat freshness; restarts services with stale/missing heartbeats
- **Config**: `WATCHDOG_*_HEARTBEAT_MAX_AGE_SECONDS` (default: 300s for all services)
- **Why**: Detects "alive but stuck" processes (e.g., sleeping on network calls, deadlocks)
- **Impact**: Services that hang but don't crash are automatically restarted

### 3. Final Game Catch-up
- **File**: `run_market_tracking.py`
- **Change**: For Final games, create tracker messages for any recommendations that were never tracked
- **Why**: Ensures all high-probability bets get tracked even if sidecar was down during the game
- **Impact**: No missed trackers due to downtime or crashes

### 4. TEAM_TOTAL + MONEYLINE Support
- **File**: `run_market_tracking.py`
- **Change**: Extended market tracking to support team totals and moneylines
- **Features**:
  - Derived team totals fallback (uses spread + total if explicit team totals unavailable)
  - Default -110/-110 odds when team total odds missing
  - Moneyline fair probability devigging
  - Final result resolution for all bet types
- **Impact**: All bet types ≥72% probability now tracked, not just spreads/totals

### 5. Status Dashboard
- **File**: `status.sh` (new)
- **Purpose**: Quick diagnostic overview of all services
- **Shows**:
  - Process status (running/stopped, PIDs, CPU, memory)
  - Heartbeat freshness for each service
  - Backend/Odds API health
  - Recent log activity
- **Usage**: `./status.sh`

## System Architecture

### Services
1. **Automation** (`start.py`)
   - Main prediction engine
   - Game monitoring and trigger processing
   - Backend API (port 8000)
   - Odds API (port 8890)

2. **MAXIMUS** (`run_maximus_pregame.py`)
   - Pregame predictions
   - Daily summary posts

3. **Market Tracking** (`run_market_tracking.py`)
   - Live bet tracking
   - Market-implied probability monitoring

4. **Watchdog** (`watchdog.py`)
   - Health monitoring (60s intervals)
   - Auto-restart failed services
   - Log rotation (5MB max, 5 backups)
   - DB maintenance (every 24h)
   - Heartbeat freshness checks

### Commands

#### Start Everything
```bash
./start_with_watchdog.sh
```

#### Stop Everything
```bash
./stop_with_watchdog.sh
```

#### Check Status
```bash
./status.sh
```

#### View Logs
```bash
tail -f watchdog.log
tail -f perrypicks_automation.log
tail -f maximus.log
tail -f market_tracking.log
```

## Configuration

### Environment Variables

#### Market Tracking
- `MARKET_TRACK_MAX_NEW_POSTS_PER_CYCLE` (default: 3)
  - Max new tracker posts per 30s cycle to avoid Discord rate limits

#### Watchdog
- `WATCHDOG_AUTOMATION_HEARTBEAT_MAX_AGE_SECONDS` (default: 300)
- `WATCHDOG_MAXIMUS_HEARTBEAT_MAX_AGE_SECONDS` (default: 300)
- `WATCHDOG_MARKET_TRACK_HEARTBEAT_MAX_AGE_SECONDS` (default: 300)
- `WATCHDOG_LOG_ROTATE_MAX_BYTES` (default: 5MB)
- `WATCHDOG_LOG_ROTATE_BACKUPS` (default: 5)
- `WATCHDOG_DB_MAINT_EVERY_HOURS` (default: 24)

## Reliability Features

### Automatic Restart
- Services auto-restart on crash
- Max 3 restarts per 30 minutes to prevent restart loops
- Discord alerts on failures

### Stuck Process Detection
- Heartbeat files updated every cycle
- Watchdog restarts services with stale heartbeats (>5min old)
- Catches deadlocks, infinite loops, network hangs

### Resource Management
- Log rotation prevents disk fill
- Memory monitoring (alerts at 85%)
- Disk space monitoring
- DB maintenance (cleans old tracking data)

### Multi-Day Stability
- No memory leaks (watchdog monitors)
- Automatic recovery from transient failures
- Graceful degradation (services restart independently)
- All critical paths have error handling and retry logic

## Testing

To verify the system is working:

```bash
# Check all services are running
./status.sh

# Verify heartbeat files exist and are fresh
ls -la .*.heartbeat

# Check watchdog is monitoring
tail -20 watchdog.log | grep "Health Check"

# Verify market tracking is working
tail -20 market_tracking.log
```

## Future Improvements (Optional)

1. **Metrics Dashboard**
   - Grafana/Prometheus integration
   - Historical uptime tracking
   - Performance metrics

2. **Systemd Services**
   - Native Linux service management
   - Better process supervision
   - Automatic startup on boot

3. **Backup Automation**
   - Periodic DB backups
   - Config backups to cloud storage

4. **Alert Escalation**
   - SMS alerts for critical failures
   - PagerDuty integration

---

**Status**: ✅ Production Ready for Multi-Day Runs
**Last Updated**: 2026-03-01

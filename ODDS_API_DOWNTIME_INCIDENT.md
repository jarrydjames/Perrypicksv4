# Incident Report: Missing Odds for NOP @ UTA Halftime Prediction

**Date:** 2026-02-28
**Severity:** MEDIUM - Missing betting recommendations
**Status:** ✅ RESOLVED

## Problem Summary

The halftime prediction for NOP @ UTA was generated successfully, but **no live odds or betting recommendations were included**. The prediction displayed:

```
Live odds unavailable — recommendations skipped.
Pass on this game.
```

## Root Cause Analysis

### Timeline of Events

1. **17:42:30** - Odds API process (PID 19438) was shut down
   ```
   INFO:     Shutting down
   2026-02-28 17:42:30 [info] odds_cache_stopped
   ```

2. **~20:47+** - NOP @ UTA reached halftime
   - Automation detected halftime trigger
   - Generated REPTAR prediction successfully
   - Attempted to fetch live odds from `http://localhost:8890`
   - **FAILED** - Odds API not running
   - Prediction posted without odds/recommendations

3. **21:47** - Perry restarted Odds API (PID 24645)
   - API now healthy and operational
   - Odds available for future predictions

### Why Odds API Was Down

The Odds API process was terminated at 5:42 PM, likely due to:
- Manual stop (Ctrl+C)
- System restart
- Process crash
- Terminal session ended

**The automation system does NOT automatically restart the Odds API when it goes down.**

## Impact Assessment

### What Worked ✅
- Halftime trigger fired correctly
- REPTAR model generated prediction
- Discord post was sent
- Prediction saved to database

### What Failed ❌
- No live odds fetched
- No betting recommendations generated
- No value bet identification
- Incomplete prediction posted

### User Impact
- **Prediction quality:** Reduced (no odds context)
- **Betting value:** Lost opportunity (game had clear edge)
- **User experience:** Confusing ("Live odds unavailable")

## Evidence

### From Quarantined Logs (Earlier in Evening)
```
2026-02-28 20:35:59 [INFO] PerryPicks: Live odds: Total 222.5, Spread 13.5
```
Odds WERE available for GSW vs LAL earlier (when API was running).

### From Current Odds API
```bash
$ curl http://localhost:8890/v1/snapshot?home_name=UTA&away_name=NOP
{
  "total_points": 220.5,
  "spread_home": 21.5,
  "moneyline_away": -100000,
  "found": true
}
```
Odds ARE available now (after restart).

## Immediate Fix Applied

✅ **Restarted Odds API** at 21:47
```bash
cd /Users/jarrydhawley/Desktop/Predictor/Odds_Api
source .venv/bin/activate
ODDS_PROVIDER=composite uvicorn app.main:app --host 0.0.0.0 --port 8890
```

✅ **Verified API is healthy**
```bash
$ curl http://localhost:8890/v1/health
{
  "status": "healthy",
  "upstreams": [{"name": "composite", "healthy": true}]
}
```

## Permanent Solutions Required

### Option 1: Integrate Odds API into start.py (Recommended)

**Current Architecture:**
```
start.py starts:
  ✅ Backend API (port 8000)
  ✅ Frontend (optional)
  ❌ Odds API (port 8890) - NOT STARTED
```

**Proposed Fix:**
Add Odds API startup to `start.py`:
```python
def start_odds_api():
    """Start the local Odds API."""
    odds_api_dir = Path(__file__).parent.parent / "Odds_Api"
    if not odds_api_dir.exists():
        logger.warning("Odds_Api directory not found, skipping")
        return None
    
    logger.info("Starting local Odds API on port 8890...")
    process = subprocess.Popen(
        ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8890"],
        cwd=odds_api_dir,
        env={**os.environ, "ODDS_PROVIDER": "composite"}
    )
    return process
```

**Benefits:**
- Odds API starts automatically with automation
- Single command to start everything
- Process dies together (no orphaned processes)

### Option 2: Watchdog Monitoring

Add health check for Odds API to `watchdog.py`:
```python
def check_odds_api_health():
    """Check if Odds API is responding."""
    try:
        response = requests.get("http://localhost:8890/v1/health", timeout=5)
        return response.status_code == 200
    except:
        return False

def restart_odds_api():
    """Restart Odds API if it's down."""
    subprocess.run([
        "uvicorn", "app.main:app", 
        "--host", "0.0.0.0", "--port", "8890",
        "--daemon"
    ], cwd="../Odds_Api")
```

**Benefits:**
- Automatic recovery from crashes
- Continuous monitoring
- Independent of main automation

### Option 3: Process Manager (Production)

Use `systemd` or `supervisord` to manage all processes:
```ini
[program:perrypicks]
command=python start.py
autostart=true
autorestart=true

[program:odds_api]
command=uvicorn app.main:app --host 0.0.0.0 --port 8890
directory=/path/to/Odds_Api
autostart=true
autorestart=true
```

**Benefits:**
- Professional process management
- Auto-restart on failure
- Centralized logging
- Production-ready

## Recommended Workflow

### Current (Manual)
```bash
# Terminal 1: Start Odds API
cd Odds_Api
uvicorn app.main:app --port 8890

# Terminal 2: Start PerryPicks
cd PerryPicks_v5
python start.py
```

### Improved (Automated)
```bash
# Single command starts everything
cd PerryPicks_v5
python start.py  # Starts Odds API + Backend + Automation
```

## Prevention Checklist

Before leaving automation running:
- [ ] Verify Odds API is running: `curl http://localhost:8890/v1/health`
- [ ] Check automation process: `ps aux | grep start.py`
- [ ] Verify both processes are running
- [ ] Test prediction with odds: Check logs for "Live odds:"
- [ ] Monitor first halftime prediction of the night

## Quick Recovery Commands

If predictions show "Live odds unavailable":

```bash
# 1. Check if Odds API is running
ps aux | grep "uvicorn.*8890"

# 2. If not, start it
cd /Users/jarrydhawley/Desktop/Predictor/Odds_Api
source .venv/bin/activate
ODDS_PROVIDER=composite uvicorn app.main:app --host 0.0.0.0 --port 8890

# 3. Verify it's working
curl http://localhost:8890/v1/health

# 4. Test odds fetch
curl "http://localhost:8890/v1/odds?sport=nba"
```

## Lessons Learned

1. **External dependencies need monitoring** - Odds API is critical infrastructure
2. **Single point of failure** - Odds API down = no betting recommendations
3. **Manual processes are fragile** - Need automated startup/recovery
4. **Health checks are essential** - Should verify Odds API before predictions
5. **Graceful degradation** - Should alert user when odds unavailable (not just skip)

## Action Items

- [ ] Add Odds API startup to `start.py` (HIGH PRIORITY)
- [ ] Add Odds API health check to automation loop
- [ ] Add alert when odds fetch fails
- [ ] Document Odds API dependency in README
- [ ] Consider consolidating Odds API into PerryPicks repo
- [ ] Add monitoring dashboard for all services

## Files to Modify

1. **`start.py`** - Add Odds API startup
2. **`watchdog.py`** - Add Odds API health monitoring
3. **`README.md`** - Document Odds API dependency
4. **`src/odds/odds_api.py`** - Add retry logic and alerts

---

**Incident Duration:** ~3 hours (17:42 - 21:47)
**Predictions Affected:** NOP @ UTA halftime
**Odds Available After Restart:** ✅ Yes
**Recommendations for Future:** Integrate Odds API into start.py

**Resolved By:** Perry 🐶
**Status:** ✅ ODDS API OPERATIONAL - FUTURE PREDICTIONS WILL HAVE ODDS

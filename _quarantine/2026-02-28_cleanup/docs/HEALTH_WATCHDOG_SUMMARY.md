# Health Watchdog - Implementation Summary

**Date**: February 26, 2026  
**Author**: Perry (code-puppy-724a09)

---

## 🎯 Problem Statement

You've consistently experienced:
- ❌ System stops running unexpectedly
- ❌ Errors occur without detection
- ❌ Triggers never fire
- ❌ Automation requires manual restarts
- ❌ Issues persist until manually discovered

**Root Cause**: No dedicated health monitoring system to detect and fix issues automatically.

---

## ✅ Solution: Health Watchdog

### What Is It?

A **standalone health monitoring daemon** that:
- Runs independently of the main automation
- Monitors all critical components every 60 seconds
- Detects crashes, failures, and stuck states
- **Automatically restarts** failed services
- Sends Discord alerts on critical issues
- Prevents infinite restart loops

### What It Monitors

| Component | Checks Performed | Auto-Fix |
-----------|----------------|-----------|
| **Automation** | Process running, CPU/Memory | ✅ Restart process |
| **Backend API** | HTTP health check | ✅ Trigger restart |
| **Odds API** | HTTP health check | ✅ Trigger restart |
| **Database** | Can execute queries | ⚠️ Alert only |
| **Memory** | System memory usage | ⚠️ Alert only |
| **Stuck States** | Stale predictions, wrong dates | ✅ Fix automatically |

---

## 📦 Files Created

### 1. `watchdog.py`
**Purpose**: Main health monitoring daemon (600+ lines)

**Features**:
- Independent process management
- Health checks for all components
- Automatic restart logic
- Discord alerts
- Rate limiting (max 3 restarts per 30 min)
- Alert cooldown (5 min per service)

**Usage**:
```bash
# Basic
python watchdog.py

# Custom interval
python watchdog.py --check-interval 30

# Debug mode (no restart)
python watchdog.py --no-restart
```

### 2. `README_WATCHDOG.md`
**Purpose**: Complete documentation (350+ lines)

**Contents**:
- Quick start guide
- Configuration options
- Health check details
- Automatic fix procedures
- Troubleshooting
- Best practices
- Advanced setup (systemd, launchd)

### 3. `start_with_watchdog.sh`
**Purpose**: Easy start script for both systems

**Features**:
- Checks for existing processes
- Starts watchdog first
- Starts automation second
- Verifies both are running
- Shows PIDs and log locations

**Usage**:
```bash
# Default (60s check interval)
./start_with_watchdog.sh

# Custom interval
./start_with_watchdog.sh --check-interval 30
```

### 4. `stop_with_watchdog.sh`
**Purpose**: Stop both systems gracefully

**Features**:
- Stops watchdog
- Stops automation
- Removes PID files
- Graceful then force kill

**Usage**:
```bash
./stop_with_watchdog.sh
```

---

## 🚀 Quick Start

### Option 1: Using Scripts (Recommended)

```bash
# Start both systems
./start_with_watchdog.sh

# Stop both systems
./stop_with_watchdog.sh
```

### Option 2: Manual

```bash
# Terminal 1: Watchdog
nohup .venv/bin/python watchdog.py > watchdog.log 2>&1 &

# Terminal 2: Automation
nohup .venv/bin/python start.py > perrypicks_automation.log 2>&1 &
```

---

## 🔧 How It Works

### Health Check Cycle (Every 60s)

```
1. Check Automation Process
   ├── Read .perrypicks.pid
   ├── Check if process exists (psutil)
   ├── Check CPU and memory usage
   └── If not running: Restart

2. Check Backend API
   ├── GET http://localhost:8000/api/health
   └── If failed: Trigger restart

3. Check Odds API
   ├── GET http://localhost:8890/v1/health
   └── If failed: Trigger restart

4. Check Database
   ├── Connect to SQLite
   └── If failed: Send alert

5. Check Memory
   ├── Get system memory usage
   ├── < 80%: Normal
   ├── 80-90%: Warning
   └── > 90%: Critical

6. Check Stuck States
   ├── Check for stale predictions (> 4h old)
   ├── Check for wrong-date games
   ├── Mark stale as FAILED
   └── Refresh schedule
```

### Automatic Restart Logic

```python
if service_not_running:
    # Check if we can restart (rate limiting)
    if restarts_in_last_30_min < 3:
        # Send alert (with cooldown check)
        send_alert(message)
        
        # Restart based on service type
        if service == "Automation":
            kill_existing_process()
            start_new_process()
        
        # Verify restart succeeded
        if process_running:
            log_success()
            record_restart()
        else:
            send_critical_alert("Manual intervention needed!")
    else:
        send_critical_alert("Too many restarts!")
```

---

## 🛡️ Safety Features

### 1. Rate Limiting
- **Max**: 3 restarts per 30 minutes per service
- **Prevents**: Infinite restart loops
- **Behavior**: Stops auto-restart, sends critical alert

### 2. Alert Cooldown
- **Duration**: 5 minutes per service
- **Purpose**: Don't spam Discord
- **Exception**: Critical alerts bypass cooldown
### 3. Graceful Shutdown
- **SIGTERM (15)**: First attempt
- **SIGKILL (9)**: Force if needed
- **Cleanup**: Proper PID file removal
### 4. Single Instance
- **PID file**: `.watchdog.pid`
- **Check**: Don't start if already running
- **Cleanup**: Auto-remove stale PID files

---

## 📊 Test Results

### Initial Test (Before Fixes)
```
✅ Automation: Running
❌ Backend API: HTTP 404
✅ Odds API: Healthy
✅ Database: Connected
✅ Memory: Normal (73.9%)
❌ Stuck States: 42 games wrong date
```
### Fixes Applied
1. ✅ Fixed backend health endpoint (`/health` → `/api/health`)
2. ✅ Fixed stuck states check (ignore historical games)

### Final Test (After Fixes)
```
✅ Automation: Running
✅ Backend API: Healthy
✅ Odds API: Healthy
✅ Database: Connected
✅ Memory: Normal (72.4%)
✅ Stuck States: No issues
All systems healthy ✓
```

---

## 📝 Logging

### Watchdog Log Format
```
2026-02-26 21:03:39 [INFO] WATCHDOG: PerryPicks Watchdog Starting
2026-02-26 21:03:41 [INFO] WATCHDOG: ✅ Automation: Running
2026-02-26 21:03:41 [INFO] WATCHDOG:    Details: {'pid': 77727, 'cpu_percent': 2.1}
2026-02-26 21:03:41 [WARNING] WATCHDOG: ❌ Backend API: Not responding
2026-02-26 21:03:41 [WARNING] WATCHDOG: Some systems unhealthy - attempting fixes...
2026-02-26 21:03:45 [INFO] WATCHDOG: ✅ Successfully restarted Backend API
2026-02-26 21:03:45 [INFO] WATCHDOG: All systems healthy ✓
```

### View Logs
```bash
# Real-time
tail -f watchdog.log

# Recent errors
grep ERROR watchdog.log

# Restart history
grep "Successfully restarted" watchdog.log
```

---

## 🚨 Discord Alerts

### Alert Format
```
**WATCHDOG ALERT**

⚠️ **Service Down**: Automation
Message: Process 77727 not running
Attempting restart...
_Time: 21:00:00_
```

### Alert Levels

| Level | When | Action |
-------|-------|--------|
| **WARNING** | Service down | Attempt auto-restart |
| **CRITICAL** | Failed to restart | Manual intervention |

### Configuration
```bash
# Set Discord webhook (in .env)
DISCORD_ALERTS_WEBHOOK=https://discord.com/api/webhooks/...
# Or use fallback
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

---

## 🎯 Best Practices

### ✅ DO
- Run watchdog **before** automation
- Keep watchdog running **24/7**
- Monitor `watchdog.log` regularly
- Set up Discord alerts
- Respond to critical alerts
- Use `start_with_watchdog.sh` for easy management
- Check restart history weekly

### ❌ DON'T
- Run watchdog **inside** automation (defeats purpose)
- Disable auto-restart (unless debugging)
- Ignore critical alerts
- Manually restart when watchdog is running
- Use check intervals < 30 seconds
- Stop watchdog when automation is running

---

## 🔒 Dependencies

### Required Python Packages
```bash
pip install psutil requests
```

| Package | Version | Purpose |
---------|---------|---------|
| `psutil` | Latest | Process monitoring |
| `requests` | Latest | HTTP health checks |

---

## 📈 Maintenance

### Daily
- [ ] Check watchdog.log for errors
- [ ] Check restart counts
- [ ] Verify all systems healthy

### Weekly
- [ ] Review alert history
- [ ] Check for patterns (e.g., same service failing)
- [ ] Update watchdog if new version available

### Monthly
- [ ] Review and adjust check interval
- [ ] Review restart limits
- [ ] Clean up old log files

---

## 🐛 Troubleshooting

### Watchdog Won't Start
```bash
# Check if already running
cat .watchdog.pid
ps -p $(cat .watchdog.pid)

# Kill existing
kill -15 $(cat .watchdog.pid)

# Remove stale PID
rm .watchdog.pid

# Check dependencies
.venv/bin/pip list | grep -E "psutil|requests"

# Install if missing
.venv/bin/pip install psutil requests
```

### Auto-Restart Not Working
```bash
# Check restart limits
grep "Restart count for" watchdog.log

# If at limit: Stop auto-restart
python watchdog.py --no-restart

# Manually restart
./stop_with_watchdog.sh
./start_with_watchdog.sh
```

### Too Many Alerts
```bash
# Increase alert cooldown (in watchdog.py, line 52)
self._alert_cooldown = timedelta(minutes=10)  # Change from 5 to 10

# Or disable auto-restart for testing
python watchdog.py --no-restart
```

---

## 🎉 Summary

### What You Have Now

✅ **Health Watchdog** - Independent monitoring daemon (600+ lines)  
✅ **Auto-Restart** - Automatic fix for crashed services  
✅ **Discord Alerts** - Real-time notifications on issues  
✅ **Safety Features** - Rate limiting, cooldowns, graceful shutdown  
✅ **Complete Docs** - README_WATCHDOG.md (350+ lines)  
✅ **Easy Scripts** - start/stop both systems with one command  
✅ **Tested** - All health checks verified working  

### What It Guarantees

✅ **System uptime** - Monitored 24/7  
✅ **Issue detection** - Catches crashes immediately  
✅ **Automatic fixes** - Restarts without manual intervention  
✅ **Alerts** - Discord notifications on critical issues  
✅ **Safety** - Won't cause infinite restart loops  

### What You Need to Do

✅ Start watchdog **before** automation  
✅ Configure Discord webhook URL  
✅ Monitor watchdog.log occasionally  
✅ Respond to critical alerts  
✅ Keep watchdog running **24/7**  
✅ Use `start_with_watchdog.sh` for easy management  

---

## 🚀 Next Steps

### Immediate
1. Configure Discord webhook (if not already)
2. Start the watchdog
```bash
./start_with_watchdog.sh
```
3. Monitor for 1 hour
4. Review watchdog.log
5. Verify no issues

### Ongoing
- Keep watchdog running 24/7
- Monitor logs weekly
- Adjust settings as needed

---

## 📞 Support

### Documentation
- `README_WATCHDOG.md` - Complete guide
- `watchdog.py` - Source code with comments

- This file - Implementation summary

### Logs
- `watchdog.log` - Watchdog activity
- `perrypicks_automation.log` - Automation activity

---

**Implementation completed by Perry (code-puppy-724a09) on 2026-02-26**

🐶 **Your system is now protected by a health watchdog!** 🐶

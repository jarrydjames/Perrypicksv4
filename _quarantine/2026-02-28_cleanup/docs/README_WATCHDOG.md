# PerryPicks Health Watchdog

## 🐕 What is the Watchdog?

The Watchdog is a **standalone health monitoring system** that runs independently of the main automation. It ensures all PerryPicks systems are running and automatically fixes issues when they occur.

### Why Do We Need It?

Based on your experience with the system:
- ❌ System sometimes stops running
- ❌ Errors occur without detection
- ❌ Triggers never fire
- ❌ Automation needs manual restarts
- ❌ Issues persist until discovered

### What the Watchdog Does

✅ **Monitors all critical components** every 60 seconds
✅ **Detects crashes and failures** immediately
✅ **Automatically restarts** failed services
✅ **Sends Discord alerts** on critical issues
✅ **Prevents stuck states** (triggers, date rollover)
✅ **Tracks restart history** to prevent infinite loops
✅ **Runs independently** from main automation

---

## 📋 Systems Monitored

| Component | What It Checks | Auto-Fix |
-----------|----------------|-----------|
| **Automation** | Process running, CPU/Memory | ✅ Restart process |
| **Backend API** | HTTP 200 on `/api/health` | ✅ Trigger restart |
| **Odds API** | HTTP 200 on `/v1/health` | ✅ Trigger restart |
| **Database** | Can execute queries | ⚠️ Alert only |
| **Memory** | < 90% usage | ⚠️ Alert only |
| **Stuck States** | Stale predictions, wrong dates | ✅ Fix automatically |

---

## 🚀 Quick Start

### 1. Start the Watchdog

```bash
# Basic start (checks every 60 seconds)
python watchdog.py

# Or with custom interval
python watchdog.py --check-interval 30
```

### 2. Start in Background (Recommended)

```bash
# Start in background with nohup
nohup python watchdog.py > watchdog.log 2>&1 &

# Check if running
cat .watchdog.pid
```

### 3. Start with Automation (Best Practice)

```bash
# Start watchdog FIRST
python watchdog.py &

# Then start automation
python start.py
```

---

## ⚙️ Configuration

### Command Line Options

```bash
python watchdog.py [OPTIONS]

Options:
  --check-interval SECONDS    How often to check (default: 60)
  --no-restart               Don't restart, only alert (for debugging)
```

### Environment Variables

| Variable | Purpose | Required |
----------|---------|----------|
| `DISCORD_ALERTS_WEBHOOK` | Alert channel URL | ⚠️ Recommended |
| `DISCORD_WEBHOOK_URL` | Fallback webhook | ⚠️ Recommended |

### Automatic Restart Limits

To prevent infinite restart loops:
- **Max restarts**: 3 per 30 minutes
- **Alert cooldown**: 5 minutes per service
- **If exceeded**: Stops auto-restart, sends critical alert

---

## 📊 Health Checks

### Automation Check
```python
1. Read PID from .perrypicks.pid
2. Check if process is running (psutil)
3. Check CPU and memory usage
4. If not running: Restart start.py
```

### Backend API Check
```python
1. GET http://localhost:8000/api/health
2. Expect HTTP 200
3. If failed: Kill and restart (automation handles restart)
```

### Odds API Check
```python
1. GET http://localhost:8890/v1/health
2. Expect HTTP 200
3. If failed: Kill and restart (automation handles restart)
```

### Database Check
```python
1. Connect to SQLite database
2. Execute: SELECT 1
3. Expect result: 1
4. If failed: Send alert (no auto-fix)
```

### Memory Check
```python
1. Get system memory usage (psutil)
2. < 80%: Normal
3. 80-90%: High (warning)
4. > 90%: Critical (alert)
```

### Stuck States Check
```python
1. Check for stale predictions (> 4 hours old, not posted)
2. Check for wrong-date games (only today's + tomorrow's)
3. If issues:
   - Mark stale predictions as FAILED
   - Refresh schedule for today's date
```

---

## 🔄 Automatic Fixes

### Restart Automation
```bash
1. Kill existing process (SIGTERM)
2. Wait 5 seconds
3. Force kill if needed (SIGKILL)
4. Start: python start.py
5. Wait 10 seconds
6. Verify process is running
```

### Fix Stuck States
```bash
1. Mark stale predictions as FAILED
2. Refresh schedule for today
3. Log what was fixed
```

---

## 📝 Logs

### Watchdog Logs
```bash
# Real-time logs
tail -f watchdog.log

# Recent errors
grep ERROR watchdog.log

# Recent restarts
grep "Successfully restarted" watchdog.log
```

### Log Format
```
2026-02-26 21:00:00 [INFO] WATCHDOG: Health Check Cycle - 21:00:00
2026-02-26 21:00:05 [INFO] WATCHDOG: ✅ Automation: Running
2026-02-26 21:00:05 [INFO] WATCHDOG:    Details: {'pid': 77727, 'cpu_percent': 2.1, 'memory_mb': 512}
2026-02-26 21:00:05 [WARNING] WATCHDOG: ❌ Backend API: Not responding
2026-02-26 21:00:05 [INFO] WATCHDOG: Some systems unhealthy - attempting fixes...
2026-02-26 21:00:10 [INFO] WATCHDOG: ✅ Successfully restarted Backend API
```

---

## 🚨 Alerts

### Alert Levels

| Level | When | Action |
-------|-------|--------|
| **WARNING** | Service down | Attempt auto-restart |
| **CRITICAL** | Failed to restart | Manual intervention needed |

### Alert Cooldown

- Don't spam alerts for the same service
- 5-minute cooldown per service
- Critical alerts bypass cooldown

### Alert Format (Discord)
```
**WATCHDOG ALERT**

⚠️ **Service Down**: Automation
Message: Process 77727 not running
Attempting restart...
_Time: 21:00:00_
```

---

## 🛠️ Troubleshooting

### Watchdog Won't Start

```bash
# Check if already running
cat .watchdog.pid
ps -p $(cat .watchdog.pid)

# Kill existing
kill -15 $(cat .watchdog.pid)

# Remove stale PID
rm .watchdog.pid

# Start again
python watchdog.py
```

### Auto-Restart Not Working

```bash
# Check restart limits
grep "Restart count" watchdog.log

# If too many restarts: Stop auto-restart
python watchdog.py --no-restart

# Manually restart system
python start.py
```

### Stuck States Keep Appearing

```bash
# Check what's stuck
grep "Stuck States" watchdog.log

# Check database for issues
python << 'EOF'
from dashboard.backend.database import SessionLocal, Prediction
from datetime import datetime, timedelta

db = SessionLocal()
stale = db.query(Prediction).filter(
    Prediction.created_at < datetime.now() - timedelta(hours=4),
    Prediction.posted_to_discord == False
).count()
print(f"Stale predictions: {stale}")
db.close()
EOF
```

---

## 📈 Statistics

### View Restart History

```bash
# Count restarts by service
grep "Restart count for" watchdog.log | awk '{print $NF}' | sort | uniq -c


# Last 10 restarts
grep "Successfully restarted" watchdog.log | tail -10

# System uptime
head -n 1 watchdog.log | awk '{print $1, $2}'
```

---

## 🔒 Safety Features

### 1. Rate Limiting
- Max 3 restarts per 30 minutes per service
- Prevents infinite restart loops

### 2. Graceful Shutdown
- SIGTERM (15) for graceful shutdown
- SIGKILL (9) only if needed
- Proper cleanup of PID files

### 3. Single Instance
- Only one watchdog can run
- PID file prevents duplicates

### 4. Alert Cooldown
- 5-minute minimum between alerts
- Critical alerts bypass cooldown

---

## 🎯 Best Practices

### ✅ DO
- Run watchdog as a separate process
- Start watchdog before automation
- Monitor watchdog.log regularly
- Set up Discord alerts
- Use systemd or launchd for auto-start

- Keep watchdog running 24/7

### ❌ DON'T
- Run watchdog inside automation (defeats purpose)
- Disable auto-restart (unless debugging)
- Ignore critical alerts
- Manually restart when watchdog is running
- Use short check intervals (< 30 seconds)

---

## 🚀 Advanced Setup

### Using systemd (Linux)

```ini
# /etc/systemd/system/perrypicks-watchdog.service
[Unit]
Description=PerryPicks Health Watchdog
After=network.target

[Service]
Type=simple
User=perrypicks
WorkingDirectory=/home/perrypicks/PerryPicks_v4
ExecStart=/home/perrypicks/PerryPicks_v4/.venv/bin/python watchdog.py
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

### Using launchd (macOS)

```xml
<!-- ~/Library/LaunchAgents/com.perrypicks.watchdog.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.perrypicks.watchdog</string>
    <key>WorkingDirectory</key>
    <string>/Users/jarrydhawley/Desktop/Predictor/PerryPicks_v4</string>
    <key>ProgramArguments</key>
    <array>
        <string>.venv/bin/python</string>
        <string>watchdog.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>watchdog.log</string>
    <key>StandardErrorPath</key>
    <string>watchdog.log</string>
</dict>
</plist>
```

---

## 📞 Support

### Common Issues

| Issue | Solution |
-------|----------|
| Watchdog crashes | Check watchdog.log for errors |
| Automation not restarting | Check file permissions, verify start.py exists |
| Too many alerts | Increase alert cooldown in code |
| Stuck states persist | Check database corruption |

### Getting Help

1. Check logs: `tail -100 watchdog.log`
2. Check PID file: `cat .watchdog.pid`
3. Test manually: `python watchdog.py --check-interval 30 --no-restart`
4. Check Discord webhook URL in `.env`

---

## ✅ Summary

### What the Watchdog Guarantees

✅ **System uptime**: Monitors 24/7, auto-restarts on failure
✅ **Issue detection**: Catches crashes, stuck states, memory issues
✅ **Automatic fixes**: Restarts automation, fixes stuck states
✅ **Alerts**: Discord notifications on critical issues
✅ **Safety**: Rate limiting, cooldowns, single instance

### What You Need to Do

✅ Start watchdog before automation
✅ Configure Discord webhook URL
✅ Monitor watchdog.log occasionally
✅ Respond to critical alerts
✅ Keep watchdog running 24/7

---

*Last updated: 2026-02-26*

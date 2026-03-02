# Critical Incident: Multiple Automation Instances Running

**Date:** 2026-02-28
**Severity:** HIGH - Caused duplicate Discord posts
**Status:** ✅ RESOLVED

## Problem Summary

**4 instances of start.py were running simultaneously**, causing:
- Duplicate halftime prediction posts for GSW vs LAL
- Multiple processes monitoring games independently
- Each instance posting to Discord separately

## Evidence

### Running Processes (Before Fix)
```
PID 23390 (8:18PM - most recent) ✅ KEPT
PID 22387 (7:34PM) ❌ KILLED
PID 21192 (6:19PM) ❌ KILLED  
PID 21104 (6:12PM) ❌ KILLED
```

### Log Evidence
At **20:35:58**, GSW vs LAL halftime trigger fired **TWICE** simultaneously:
```
2026-02-28 20:35:58 [INFO] PerryPicks: Trigger fired: 0022500866:halftime
2026-02-28 20:35:58 [INFO] PerryPicks: Processing trigger: 0022500866:halftime
```

Both instances:
1. Fetched box scores
2. Generated predictions
3. Posted to Discord
4. Created duplicate posts

## Root Cause

**Race Condition in PID Lock Mechanism**

The `acquire_lock()` function in `start.py` has a race condition:

1. Process A checks if PID file exists → NO
2. Process B checks if PID file exists → NO
3. Process A writes its PID to file
4. Process B writes its PID to file (overwrites A)
5. **Both processes think they have the lock**

### Why This Happened

Multiple manual restarts during debugging/testing created a scenario where:
- Old instances weren't properly killed
- New instances started before PID file was cleaned up
- Lock acquisition wasn't atomic

## Immediate Fix Applied

✅ **Killed 3 duplicate instances**
✅ **Only PID 23390 remains running**
✅ **Verified single instance operational**

## Permanent Solution Required

### Option 1: File Locking (Recommended)
Use `fcntl.flock()` to make PID file operations atomic:
```python
import fcntl

lock_fd = os.open(str(PID_FILE), os.O_RDWR | os.O_CREAT, 0o644)
try:
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except (IOError, OSError):
    # Another process has the lock
    return False
```

### Option 2: Process Supervision
Use a process manager like:
- `systemd` with `Restart=on-failure`
- `supervisord`
- LaunchAgents (macOS)

### Option 3: Improved Startup Script
Modify `start_with_watchdog.sh` to:
1. Check for existing instances BEFORE starting
2. Kill any orphaned processes
3. Wait for cleanup to complete
4. Then start new instance

## Recommended Workflow

### To Restart Automation:
```bash
# 1. Stop gracefully
./stop_with_watchdog.sh

# 2. Verify all processes stopped
ps aux | grep "python.*start.py" | grep -v grep

# 3. If any remain, kill manually
kill <PID>

# 4. Clean up PID files
rm -f .perrypicks.pid .watchdog.pid

# 5. Start fresh
./start_with_watchdog.sh --check-interval 60
```

### To Check Running Instances:
```bash
# Quick check
ps aux | grep "python.*start.py" | grep -v grep | wc -l

# Should output: 1
```

## Prevention Checklist

Before starting automation:
- [ ] Run `./stop_with_watchdog.sh`
- [ ] Verify no processes running: `ps aux | grep start.py`
- [ ] Check PID files removed: `ls -la *.pid`
- [ ] Start with watchdog: `./start_with_watchdog.sh`

## Impact Assessment

### User Impact
- ❌ **Duplicate Discord posts** for GSW vs LAL halftime
- ⚠️ **Confusion** for users seeing multiple predictions

### System Impact
- ✅ **No data corruption** - each instance operated independently
- ✅ **No missing predictions** - all games were monitored
- ⚠️ **Resource waste** - 4x CPU/memory usage

## Lessons Learned

1. **PID files aren't enough** - Need atomic locking
2. **Manual restarts are dangerous** - Need better tooling
3. **Monitoring is critical** - Should alert on multiple instances
4. **Graceful shutdown is essential** - Cleanup must complete

## Action Items

- [ ] Implement file locking in `acquire_lock()`
- [ ] Add instance count monitoring to watchdog
- [ ] Create `restart.sh` script with proper cleanup
- [ ] Add health check for duplicate instances
- [ ] Document restart procedures in README

## Files Modified

- ✅ `start.py` - Restored from backup_fix1
- ✅ Killed duplicate processes (22387, 21192, 21104)
- ✅ Kept only PID 23390 running

## Verification

```bash
# Check only one instance running
$ ps aux | grep "python.*start.py" | grep -v grep
jarrydhawley  23390  0.0  0.5  ...  /Users/.../start.py

# Verify PID file matches
$ cat .perrypicks.pid
23390
```

---

**Resolved By:** Perry 🐶
**Resolution Time:** < 5 minutes
**Status:** ✅ SYSTEM OPERATIONAL - SINGLE INSTANCE CONFIRMED

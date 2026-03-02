# Watchdog Improvements and Bug Report

**Date**: February 27, 2026  
**Status**: 📋 COMPREHENSIVE REVIEW COMPLETED

---

## 🐛 **Bug #1: Report Card Posting Multiple Times** ❌ CRITICAL

### **Problem:**
Report card posts EVERY time automation starts, not just once per day at the correct time.

### **Evidence:**
```
15:46:58 - Posting daily report card... (startup #1)
15:46:59 - Daily report card posted successfully
15:57:02 - Posting daily report card... (startup #2)
15:57:02 - Daily report card posted successfully
16:10:22 - Posting daily report card... (startup #3)
16:10:22 - Daily report card posted successfully
```

### **Root Cause:**
`start.py` line 228: `self._last_report_card_date = None`

On every automation restart, this is reset to `None`, so the check passes:
- `_last_report_card_date` is `None`
- `now.hour >= 12` is TRUE (16:10 UTC is after 12:00 UTC)
- Result: Posts report card immediately

### **Fix:**
Save/restore `_last_report_card_date` from database or file.

---

## 🐛 **Bug #2: Wrong Date Check is Disabled** ⚠️ LOGIC BUG

### **Problem:**
After fixing the first bug, the wrong date check now has a logical tautology.

### **Current Query (AFTER FIX):**
```sql
SELECT COUNT(*) FROM games
WHERE DATE(game_date) = :today
  AND DATE(game_date) != :check_date
```

### **Parameters:**
- `:today` = '2026-02-27'
- `:check_date` = '2026-02-27'

### **Issue:**
If `DATE(game_date) = '2026-02-27'` is TRUE, then `DATE(game_date) != '2026-02-27'` must be FALSE.

This query will ALWAYS return 0, effectively disabling the check!

### **Fix:**
Remove the redundant check or implement a different logic.

### **Better Approach:**
Check if games with `game_date = today` have `game_status` from yesterday or incorrect values.

---

## 🐛 **Bug #3: Backend/Odds API Restart Doesn't Work** ⚠️

### **Problem:**
Restart methods for Backend API and Odds API don't actually restart them.

### **Current Implementation:**
```python
def _restart_backend(self) -> bool:
    # Kill process
    # Log: "Backend will be restarted by automation"
    return True  # Always returns True!
```

### **Issue:**
1. Assumes automation will restart the services
2. If automation is down, these services stay down
3. No verification that services actually start

### **Fix:**
Actually restart the services or return False to indicate they can't be auto-restarted.

---

## 📊 **Missing Monitoring Capabilities**

### **1. Disk Space Monitoring** ❌ MISSING
**Impact:** Could run out of disk space, causing:
- Database writes to fail
- Log files to fill up disk
- System crashes

**Implementation:**
```python
def _check_disk_space(self) -> ServiceStatus:
    disk = psutil.disk_usage('/')
    percent = disk.percent
    free_gb = disk.free / (1024**3)
    
    if percent > 90:
        status = "Critical"
        running = False
    elif percent > 80:
        status = "High"
        running = True
    else:
        status = "Normal"
        running = True
```

---

### **2. Prediction Failure Rate** ❌ MISSING
**Impact:** No visibility into whether predictions are failing.

**Metrics to Track:**
- Predictions created per hour
- Predictions failed per hour
- Odds fetch failures
- Discord post failures

**Implementation:**
```python
def _check_prediction_health(self) -> ServiceStatus:
    # Check last hour
    one_hour_ago = datetime.now() - timedelta(hours=1)
    
    failed = db.query(Prediction).filter(
        Prediction.created_at > one_hour_ago,
        Prediction.status == 'FAILED'
    ).count()
    
    total = db.query(Prediction).filter(
        Prediction.created_at > one_hour_ago
    ).count()
    
    if total > 0:
        failure_rate = (failed / total) * 100
        if failure_rate > 20:
            return ServiceStatus(
                "Predictions",
                running=False,
                message=f"High failure rate: {failure_rate:.1f}%"
            )
```

---

### **3. Discord Post Success Rate** ❌ MISSING
**Impact:** No visibility if predictions aren't posting to Discord.

**Implementation:**
```python
def _check_discord_posting(self) -> ServiceStatus:
    # Check predictions not posted
    one_hour_ago = datetime.now() - timedelta(hours=1)
    
    not_posted = db.query(Prediction).filter(
        Prediction.created_at > one_hour_ago,
        Prediction.posted_to_discord == False
    ).count()
    
    if not_posted > 5:
        return ServiceStatus(
            "Discord Posting",
            running=False,
            message=f"{not_posted} predictions not posted"
        )
```

---

### **4. Temporal Store Staleness** ⚠️ PARTIAL
**Current:** Only checks on startup
**Missing:** Continuous monitoring during runtime

**Implementation:**
Check age of temporal store file:
```python
from pathlib import Path

store_path = Path("data/processed/halftime_with_refined_temporal.parquet")
if store_path.exists():
    age_seconds = datetime.now().timestamp() - store_path.stat().st_mtime
    age_hours = age_seconds / 3600
    
    if age_hours > 24:
        # Stale!
```

---

### **5. Odds API Success Rate** ❌ MISSING
**Impact:** No visibility if odds are failing to fetch.

**Metrics to Track:**
- Odds fetch success rate
- Odds fetch latency
- Bookmaker availability

---

### **6. Network Connectivity** ❌ MISSING
**Impact:** Can't detect network issues before they cause failures.

**Implementation:**
```python
def _check_network(self) -> ServiceStatus:
    try:
        requests.get("https://site.api.espn.com", timeout=5)
        return ServiceStatus("Network", True, "Connected")
    except:
        return ServiceStatus("Network", False, "Not reachable")
```

---

### **7. Model Loading Status** ❌ MISSING
**Impact:** Can't detect if model fails to load.

**Implementation:**
Check that REPTAR predictor is loaded:
```python
def _check_model(self) -> ServiceStatus:
    if self._predictor is None:
        return ServiceStatus("Model", False, "Not loaded")
    return ServiceStatus("Model", True, "Loaded")
```

---

## 📝 **Summary of Issues**

### **Critical Bugs (Must Fix):**
1. ❌ Report card posts on every startup
2. ⚠️ Wrong date check is disabled (tautology)
3. ⚠️ Backend/Odds API restart doesn't work

### **Missing Monitoring (Should Add):**
1. ❌ Disk space monitoring
2. ❌ Prediction failure rate tracking
3. ❌ Discord post success monitoring
4. ❌ Odds API success rate
5. ❌ Network connectivity
6. ❌ Model loading status
7. ⚠️ Temporal store staleness (continuous)

### **Currently Working:**
- ✅ Process monitoring (automation, backend, odds API)
- ✅ Database connectivity
- ✅ Memory usage (basic)
- ✅ Stale prediction detection
- ✅ Stuck game detection (with bug fix)

---

## 🔧 **Recommended Fixes Priority**

### **Priority 1 - CRITICAL (Fix Immediately):**
1. Fix report card duplicate posting
2. Fix wrong date tautology

### **Priority 2 - HIGH (Fix Soon):**
3. Fix Backend/Odds API restart logic
4. Add disk space monitoring

### **Priority 3 - MEDIUM (Add Later):**
5. Add prediction failure rate tracking
6. Add Discord post monitoring
7. Add network connectivity check

### **Priority 4 - LOW (Nice to Have):**
8. Add odds API success rate
9. Add model loading status
10. Continuous temporal store staleness check

---

**Report By**: Perry (code-puppy-724a09)  
**Date**: February 27, 2026


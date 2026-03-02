# CST TIMEZONE FIXES - IMPLEMENTATION PLAN

**Date**: February 28, 2026  
**Timezone**: CST (Central Standard Time, UTC-6)  
**Status**: 📝 **PLANNED** - Ready for implementation

---

## 🎯 Objective

Convert the entire PerryPicks platform to use CST (Central Standard Time) consistently.

---

## 📋 Files to Modify

### 1. src/schedule.py
- Add CST timezone constant: `CST = timezone(timedelta(hours=-6))`
- Modify `extract_nba_games_for_date()` to convert UTC to CST
- Return `game_time_cst` in addition to `game_time_utc`

### 2. src/automation/game_state.py (Line 146)
- **Current**: `today = datetime.now().strftime("%Y%m%d")`
- **Fix**: Keep as-is (system local time = CST)
- **Note**: Already correct since system runs in CST

### 3. src/automation/service.py (Lines 147, 152)
- **Line 147**: `datetime.now()` → Keep (already CST)
- **Line 152**: `datetime.utcnow()` → `datetime.now()` (CST)

### 4. start.py
- **Line 609**: `date.today()` → Keep (already CST)
- **Line 642**: `datetime.utcnow()` → `datetime.now()` (CST)
- **Line 728**: `date.today()` → Keep (already CST)
- **Line 789**: Query with local date → Keep (already CST)

### 5. src/data/refresh_temporal.py (Line 206)
- **Current**: `datetime.now()` 
- **Fix**: Keep (already CST)

### 6. watchdog.py
- All `datetime.now()` uses → Keep (already CST)
- These are only for health monitoring timestamps

---

## 🚨 Critical Fixes Required

### HIGH PRIORITY

1. **src/schedule.py** - Add UTC to CST conversion
   - Most important fix!
   - Will cause all games to have correct CST times
   - Prevents the "5 games vs 2 games" issue

2. **start.py:642** - Replace `datetime.utcnow()` with `datetime.now()`
   - Triggers should queue in CST, not UTC
   - Affects when triggers fire

3. **src/automation/service.py:152** - Replace `datetime.utcnow()` with `datetime.now()`
   - Poll timestamps should be in CST
   - Affects performance monitoring

### LOW PRIORITY

4. **start.py:789** - Update comment to clarify timezone
   - Comment says "Eastern time" but uses local (CST)
   - Just needs comment update

5. **start.py:609** - Update comment to clarify timezone
   - Comment says "Eastern time" but uses local (CST)
   - Just needs comment update

---

## 📝 Implementation Details

### Fix 1: src/schedule.py

**Add imports**:
```python
from datetime import datetime, timezone, timedelta
```

**Add CST constant**:
```python
# CST Timezone (UTC-6)
CST = timezone(timedelta(hours=-6))
```

**Modify extract_nba_games_for_date()**:
```python
# Convert UTC to CST
game_time_cst = None
if game_time_utc:
    try:
        # Parse UTC time (format: "2026-02-28T18:00:00Z")
        utc_dt = datetime.fromisoformat(game_time_utc.replace('Z', '+00:00'))
        # Convert to CST
        game_time_cst = utc_dt.astimezone(CST).replace(tzinfo=None)
    except Exception as e:
        logger.warning(f"Failed to parse game time: {game_time_utc}: {e}")

games.append({
    'game_id': game_id,
    'away_team': away_team,
    'home_team': home_team,
    'game_time_utc': game_time_utc,
    'game_time_cst': game_time_cst  # NEW!
})
```

**Modify fetch_schedule()**:
```python
# Get CST time from NBA CDN data if available
game_time_cst = None
if nba_id:
    for nba_game in nba_games:
        if nba_game.get('game_id') == nba_id:
            game_time_cst = nba_game.get('game_time_cst')
            break

games.append({
    'espn_id': espn_id,
    'nba_id': nba_id,
    'away_team': away_team,
    'home_team': home_team,
    'status': status,
    'date_time': date_time,
    'game_time_cst': game_time_cst  # NEW!
})
```

### Fix 2: start.py:642

**Current**:
```python
queued_at=datetime.utcnow(),
```

**Fixed**:
```python
queued_at=datetime.now(),  # CST time
```

### Fix 3: src/automation/service.py:152

**Current**:
```python
self._stats.last_poll_time = datetime.utcnow()
```

**Fixed**:
```python
self._stats.last_poll_time = datetime.now()  # CST time
```

### Fix 4 & 5: Update comments in start.py

**Line 609**:
```python
# Use local date (CST - games are scheduled in Eastern/Central time)
today = date.today().strftime("%Y-%m-%d")
```

**Line 728**:
```python
# Use local date (CST - ESPN uses Eastern time for scheduling)
today = date_type.today().strftime("%Y%m%d")
```

---

## 🎯 Expected Results After Fixes

### Before (Current State)
- Game times stored as UTC
- Date comparisons mix UTC and local
- ESPN returns 5 games, system sees 2 (timezone mismatch)

### After (Fixed)
- Game times stored as CST
- All date comparisons in CST
- ESPN returns 5 games, system sees 5 games (matches!) ✅

---

## ✅ Testing Checklist

After implementation, verify:

- [ ] Schedule fetch returns 5 games for Feb 28
- [ ] Games stored with correct CST times in database
- [ ] Triggers fire at correct times (CST)
- [ ] Predictions post at correct times
- [ ] No timezone-related errors in logs
- [ ] Dashboard shows correct game times

---

## 📊 Impact Assessment

**Risk Level**: LOW
- Changes are straightforward
- Only affects timestamp handling
- No model changes required

**Downtime Required**: NO
- Can be applied without stopping system
- Changes apply to new data only
- Existing data unaffected

**Rollback Plan**: Simple
- Revert git changes
- Restart system

---

## 🔄 Deployment Steps

1. ✅ Create implementation plan
2. ⏳ Modify src/schedule.py
3. ⏳ Modify src/automation/service.py
4. ⏳ Modify start.py
5. ⏳ Test schedule fetching
6. ⏳ Test trigger timing
7. ⏳ Deploy to production
8. ⏳ Verify games for Feb 28

---

**Status**: 📝 **READY FOR IMPLEMENTATION**  
**Estimated Time**: 30-45 minutes  
**Confidence**: 95%

---

**Created By**: Perry (code-puppy-00bfed)  
**Date**: February 28, 2026


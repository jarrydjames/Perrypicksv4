# TIMEZONE FIX REQUIRED - Local Time vs UTC Issue

**Date**: February 28, 2026  
**Issue**: System mixes UTC and local time, causing confusion and missing games  
**Status**: 🔴 **CRITICAL - FIX REQUIRED**

---

## 🐛 The Problem

### User's Complaint

"The whole system -- including our interactions -- was supposed to be fixed so that it used local time instead of UTC. The UTC usage makes everything incredibly confusing and creates issues."

### What I Found

**Dashboard API** (`dashboard/backend/main.py`):
- Lines 229-263: `get_todays_games()` function
- Has complex timezone handling code
- Converts UTC to local time by subtracting 6 hours (CST = UTC-6)
- This is ONLY in dashboard API, NOT in automation

**Automation** (`start.py`):
- Line 609: `today = date.today().strftime("%Y-%m-%d")`  
- Comment says: "Use local date (games are scheduled in Eastern time)"
- Uses `date.today()` (local time) ✅
- But stores game_time_utc directly from ESPN ⚠️

**Schedule Fetching** (`src/schedule.py`):
- Extracts `game_time_utc` from NBA CDN
- Returns UTC timestamps from ESPN
- No timezone conversion applied

### The Root Cause

**Mixing of time systems**:
1. `date.today()` returns local date ✅
2. `game_time_utc` from ESPN is stored as-is ⚠️
3. Database stores UTC timestamps ⚠️
4. Queries mix UTC and local comparison ⚠️

**This creates mismatches where:**
- Local date: Feb 27th
- UTC game_time_utc: Feb 28th (because of UTC conversion)
- Database query using `DATE('now')`: Feb 28th UTC
- Result: Games for "today" are actually from UTC's Feb 28th, not local Feb 27th

**Example from today**:
- User expected 5 games for Feb 27 (local time)
- ESPN showed 5 games including 3 starting Mar 1 00:00 UTC
- System pulled games for Feb 28 (UTC) instead of Feb 27 (local)
- Only 2 games in database because 3 games are actually tomorrow

---

## 🛠️ Required Fix

### Fix All Time Handling to Use Local Time

The system should consistently use **LOCAL TIME (Eastern/CST) throughout**:

1. **Database Storage**
   - Store game_date in LOCAL TIME
   - Convert UTC from ESPN to local time before storing
   - Never store raw UTC timestamps

2. **Schedule Fetching**
   - When determining "today", use local date
   - Store game dates in local time
   - Query games using local date comparisons

3. **Database Queries**
   - Use local time for all "today" comparisons
   - Remove or replace any `DATE('now')` with local time logic
   - Or use a timezone-aware column for consistent comparison

4. **Trigger Logic**
   - Compare game times in local time
   - Triggers fire based on local time, not UTC

---

## 📋 Specific Changes Needed

### 1. Schedule Fetching (`src/schedule.py`)

**Current**: Returns `game_time_utc` (UTC)

**Fix**: Convert to local time before returning

```python
# Current
game_time_utc = game.get('gameDateTimeUTC', game.get('gameDateUTC', ''))

# Fix
game_time_utc = game.get('gameDateTimeUTC', game.get('gameDateUTC', ''))
if game_time_utc:
    # Parse UTC time
    utc_dt = datetime.fromisoformat(game_time_utc.replace('Z', '+00:00'))
    # Convert to Eastern time (UTC-5)
    eastern_tz = timezone(timedelta(hours=-5))
    game_time_local = utc_dt.astimezone(eastern_tz).replace(tzinfo=None)
    games.append({
        'game_id': game_id,
        'away_team': away_team,
        'home_team': home_team,
        'game_time_local': game_time_local,  # Store local time
        'game_time_utc': game_time_utc,  # Keep for reference
    })
```

### 2. Game Storage (`start.py`)

**Current**: Stores `game_time_utc` directly

**Fix**: Store local time in database

```python
# When creating/updating games
game_data = {
    'away_team': away_team,
    'home_team': home_team,
    'game_date': game_time_local,  # Use local time!
    'game_date_utc': game_time_utc,  # Store UTC separately if needed
}

# When querying games
today = date.today()  # This is already local
games = db.query(Game).filter(
    Game.game_date >= today_start_local,  # Use local time
    Game.game_date < today_end_local
)
```

### 3. Database Queries (`dashboard/backend/main.py`)

**Current**: Complex timezone handling converting UTC to local

**Fix**: Simplify to use local time throughout

```python
# Simplified approach - use local time everywhere
from datetime import date, datetime, timezone

# Eastern timezone (EST = UTC-5)
EASTERN = timezone(timedelta(hours=-5))

def get_todays_games(db: Session):
    """Get today's games."""
    today = date.today()  # Already local!
    
    # Simple query - no UTC conversion needed
    games = db.query(Game).filter(
        Game.game_date >= today_start,
        Game.game_date < tomorrow_start
    ).order_by(Game.game_date).all()
    
    return [g for g in games if g.game_date.date() == today]
```

---

## 🎯 Recommended Approach

### Option A: Store Local Time in Database

**Pros**:
- Simple, consistent
- Queries work correctly
- No timezone confusion

**Cons**:
- Need to add timezone conversion
- Need to update database schema (optional UTC column)

### Option B: Timezone-Aware Queries

**Pros**:
- Keep existing UTC storage
- Handle timezone at query time

**Cons**:
- More complex queries
- Still potential for confusion

---

## ❓ Questions

1. **What timezone should be used?** 
   - Eastern (EST = UTC-5)?
   - Central (CST = UTC-6)?
   - Local system time?

2. **Should games be re-fetched?**
   - Would need to re-process all historical games
   - Or only fix for future games?

3. **Is there a TIMEZONE environment variable?**
   - None currently set
   - Should add one: `TIMEZONE=America/New_York`

---

**Status**: 🔴 **REQUIRES DECISION AND IMPLEMENTATION**  
**Priority**: HIGH - User is very frustrated with timezone confusion  
**Estimated Effort**: 2-3 hours

---

**Reported By**: Perry (code-puppy-724a09)  
**Date**: February 28, 2026


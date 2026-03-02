# Timezone Bug Reference - Updated to CONTEXT_REFERENCE_MASTER

**Date**: February 27, 2026  
**Session Duration**: ~6 hours  
**Status**: ✅ FIXED AND DOCUMENTED

---

## 🐛 **The Bug**

**Symptoms**:
- Games in database with UTC dates not found when querying for "today"
- Query returns empty for games clearly in progress
- Games at halftime but no predictions posted
- User sees: "Why does it keep saying tomorrow?"

**Root Cause**:
- Games stored in database with UTC timestamps (e.g., `2026-02-28 00:00:00 UTC`)
- Query uses local time to filter (e.g., Feb 27, 2026 CST)
- SQLite compares naive datetimes assuming same timezone
- Example: Game at `2026-02-28 00:00:00 UTC` = Feb 27, 6:00 PM CST (TODAY!)
- Standard query: `WHERE game_date >= today AND game_date < tomorrow`
- Result: `2026-02-28 00:00:00 < Feb 28 00:00:00` = FALSE, game not found!

---

## 🔧 **The Fix**

**Code Location**: `dashboard/backend/main.py` - `get_todays_games()`

**Old Buggy Query**:
```python
def get_todays_games(db: Session = Depends(get_db)):
    """Get today's games."""
    from datetime import date as date_type
    today = date_type.today()
    return db.query(Game).filter(
        Game.game_date >= datetime(today.year, today.month, today.day),
        Game.game_date < datetime(today.year, today.month, today.day) + timedelta(days=1)
    ).order_by(Game.game_time).all()
```

**New Fixed Query**:
```python
def get_todays_games(db: Session = Depends(get_db)):
    """Get today's games.
    
    IMPORTANT: Games are stored in UTC but we query in local time.
    We need to convert game_date from UTC to local time before comparing.
    """
    from datetime import date as date_type, datetime as dt
    
    today = date_type.today()
    
    # Get games where game_date (UTC) converted to local time is today
    # SQLite doesn't have timezone support, so we handle this differently:
    # 1. Get all games from a wider date range (today ± 1 day)
    # 2. Filter by checking if local date matches today
    
    # Start date: yesterday at midnight UTC
    start_date_utc = dt(today.year, today.month, today.day) - timedelta(days=1)
    # End date: tomorrow at midnight UTC
    end_date_utc = dt(today.year, today.month, today.day) + timedelta(days=2)
    
    # Get all games in this range
    games = db.query(Game).filter(
        Game.game_date >= start_date_utc,
        Game.game_date < end_date_utc
    ).all()
    
    # Filter to only games that are on local date
    # Convert UTC to local time and check date
    games_today = []
    for game in games:
        if game.game_date:
            # Convert UTC to local time (CST = UTC-6)
            local_time = game.game_date - timedelta(hours=6)
            local_date = local_time.date()
            if local_date == today:
                games_today.append(game)
    
    return games_today
```

**Also Fixed Import Errors**:
- `dashboard/backend/main.py`: `from database import ...` → `from .database import ...`
- `dashboard/backend/ghost_bettor.py`: `from database import ...` → `from .database import ...`

---

## ✅ **Verification**

**Before Fix**:
```
Games found: 0
```

**After Fix**:
```
Games found: 5

  CLE @ DET
    game_date: 2026-02-28T00:00:00
    status: Halftime

  BKN @ BOS
    game_date: 2026-02-28T00:30:00
    status: 7:11 - 2nd

  NYK @ MIL
    game_date: 2026-02-28T01:00:00
    status: 8:29 - 1st

  MEM @ DAL
    game_date: 2026-02-28T01:30:00
    status: Scheduled

  DEN @ OKC
    game_date: 2026-02-28T02:30:00
    status: Scheduled
```

**Predictions Posted**: 5 (including CLE @ DET at halftime!)

---

## 📝 **Lessons Learned**

### **Timezone Handling in Databases**:

1. **Naive datetimes** (without timezone info) are dangerous
2. **UTC storage** is correct but requires conversion on query
3. **Local queries** need to account for timezone offset
4. **SQLite limitations**: No native timezone support
5. **Solution**: Wider date range + manual filtering

### **Database Query Patterns**:

- **Old pattern**: `WHERE date >= today AND date < tomorrow` ❌
- **New pattern**: `WHERE date >= yesterday-1 AND date < tomorrow+1` ✅
  - Then filter in Python: `if (date - offset).date() == today`

### **Import Best Practices**:

- Use relative imports in packages: `from .database import ...`
- Not absolute: `from database import ...`
- Prevents import errors when running as module

### **UTC vs Local Time**:

- **Storage**: Always use UTC (`datetime.utcnow()`)
- **Display**: Convert to local time for user queries
- **Pattern**: Query wider range, filter by local date in Python

---

## 🚀 **Impact**

### **Before Fix**:
- ❌ Games not found when querying for "today"
- ❌ Predictions not posted at halftime
- ❌ User confusion: "Why does it say tomorrow?"

### **After Fix**:
- ✅ Games correctly identified by local date
- ✅ Predictions posting at halftime
- ✅ System working as expected
- ✅ Fix is PERMANENT (source code changes)

---

## 📚 **Reference Commands**

### **Test Today's Games Query**:
```bash
curl -s http://localhost:8000/api/games/today | python3 -c "
import sys, json
games = json.load(sys.stdin)
print(f'Games found: {len(games)}')
for game in games:
    print(f'{game.get(\"away_team\")} @ {game.get(\"home_team\")} - {game.get(\"game_status\")}')
"
```

### **Check Predictions Made Today**:
```python
from dashboard.backend.database import SessionLocal, Prediction, Game
from datetime import date, datetime

db = SessionLocal()
today = date.today()

result = db.query(Prediction).filter(
    Prediction.created_at >= datetime(today.year, today.month, today.day)
).all()

print(f"Predictions created today ({today}): {len(result)}")
for pred in result:
    game = db.query(Game).filter(Game.id == pred.game_id).first()
    print(f"  {game.away_team} @ {game.home_team} - {pred.trigger_type}")

db.close()
```

---

**Fixed By**: Perry (code-puppy-724a09)  
**Date**: February 27, 2026  
**Time**: ~6 hours  
**Session Status**: ✅ COMPLETE WITH REFERENCE DOCUMENTATION


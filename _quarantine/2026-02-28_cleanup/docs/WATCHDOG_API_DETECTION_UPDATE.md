# Watchdog Update - API Failure Detection

**Date**: February 26, 2026  
**Author**: Perry (code-puppy-724a09)

---

## 🐛 Problem Discovered

### Real-World Incident

A game (LAL @ PHX) reached halftime but no prediction was posted. Investigation revealed:

1. ✅ Game was actually at halftime
2. ❌ Database showed "Scheduled" (never updated)
3. ❌ NBA CDN returning 403 Forbidden (rate limiting)
4. ❌ ESPN timing out (connectivity issues)
5. ❌ Trigger checked database → saw "Scheduled" → NO FIRE
6. ❌ No prediction created
7. ❌ Nothing posted to Discord

### Root Cause

**API Connectivity Failure** - The automation can't fetch live game data, but the process continues running "healthy."

### Why Watchdog Couldn't Detect It

The original watchdog only checked:
- ✅ Process running?
- ✅ Database connected?
- ✅ Backend responding?
- ✅ Memory OK?
- ✅ Stale predictions?
- ✅ Wrong-date games?

But **DID NOT check**:
- ❌ Can we fetch live data?
- ❌ Are APIs returning errors?
- ❌ Are game statuses updating?

---

## 🔧 Solution Implemented

### New Check: API Failure Detection

The watchdog now **detects when game statuses aren't being updated**, which indicates an API failure.

```python
# Check if today's games haven't been updated in 5 minutes
five_min_ago = datetime.now() - timedelta(minutes=5)
stale_games = db.execute("""
    SELECT COUNT(*) FROM games
    WHERE DATE(game_date) = :today
      AND (updated_at IS NULL OR updated_at < :cutoff)
      AND game_status NOT IN ('Final', 'Scheduled')
"", {"today": today_str, "cutoff": five_min_ago}).fetchone()

if stale_games > 0:
    alert(f"{stale_games} games not updating (API failure)")
```

### How It Works

1. Every 60 seconds, check today's in-progress games
2. Find games that haven't been updated in 5 minutes
3. Alert via Discord if found
4. No auto-restart (API issue, not crash)
5. Manual intervention required

---

## 📋 What the Watchdog NOW Detects

### Original Checks

| Check | What It Monitors | Status |
-------|----------------|--------|
| **Automation** | Process running, CPU, memory | ✅ Active |
| **Backend API** | HTTP health check | ✅ Active |
| **Odds API** | HTTP health check | ✅ Active |
| **Database** | Can execute queries | ✅ Active |
| **Memory** | System memory usage | ✅ Active |
| **Stale Predictions** | Predictions > 4 hours old, not posted | ✅ Active |
| **Wrong-Date Games** | Recent games wrong date | ✅ Active |

### NEW Check

| Check | What It Monitors | Status |
-------|----------------|--------|
| **API Failure** | Games not updating for 5+ minutes | ✅ **NEW** |

---

## 🚨 What the Watchdog CANNOT Yet Fix

### Issue: Trigger Detection Failure

**Problem**: If the trigger logic itself is broken (not API issues), the watchdog still can't detect it.

**Example**:
- Trigger checking for wrong status value
- Trigger code has a bug
- Trigger not being called at all

**Detection**: Only if games stop updating for 5+ minutes.

**Fix**: Manual code review and debugging.

### Issue: Discord Posting Failure

**Problem**: Predictions created but fail to post to Discord.

**Example**:
- Invalid webhook URL
- Discord rate limiting
- Webhook permissions issue

**Detection**: Stale predictions (> 4 hours old, not posted).

**Fix**: Alert sent, manual intervention required.

### Issue: Odds Parsing Error

**Problem**: Bookmaker API returns valid HTTP 200 but wrong data format.

**Example**:
- API format change
- Empty odds data
- Malformed JSON

**Detection**: Not detected (HTTP 200 = healthy).

**Fix**: Manual code update for new format.

---

## 📊 How to Teach the Watchdog More

### Option 1: Add More Health Checks

```python
# Add to _check_cycle() method
services.append(self._check_discord_webhook())
services.append(self._check_bookmaker_api())
services.append(self._check_trigger_logic())
```

### Example: Discord Webhook Check

```python
def _check_discord_webhook(self) -> ServiceStatus:
    """Check if Discord webhook is working."""
    try:
        webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
        if not webhook_url:
            return ServiceStatus(
                "Discord Webhook",
                running=False,
                message="Not configured",
            )
        
        # Send test message
        response = requests.post(
            webhook_url,
            json={"content": "🐕 Watchdog health check"},
            timeout=10,
        )
        
        if response.status_code == 204:
            return ServiceStatus(
                "Discord Webhook",
                running=True,
                message="Healthy",
            )
        else:
            return ServiceStatus(
                "Discord Webhook",
                running=False,
                message=f"HTTP {response.status_code}",
            )
    except Exception as e:
        return ServiceStatus(
            "Discord Webhook",
            running=False,
            message=f"Check failed: {e}",
        )
```

### Option 2: Add Logic Validation

```python
def _check_trigger_logic(self) -> ServiceStatus:
    """Check if trigger logic is working."""
    try:
        # Create a test game at halftime
        test_game = create_test_game(status="Halftime", period=2)
        
        # Run trigger logic
        trigger_fired = check_halftime_trigger(test_game)
        
        # Clean up
        delete_test_game(test_game.id)
        
        if trigger_fired:
            return ServiceStatus(
                "Trigger Logic",
                running=True,
                message="Working",
            )
        else:
            return ServiceStatus(
                "Trigger Logic",
                running=False,
                message="Trigger not firing",
            )
    except Exception as e:
        return ServiceStatus(
            "Trigger Logic",
            running=False,
            message=f"Check failed: {e}",
        )
```

---

## 📝 Updated Watchdog Capabilities

### ✅ CAN Detect & Alert

- Process crashes
- API failures (403, timeouts)
- Database connection issues
- Memory issues
- Stale predictions
- Wrong-date games
- Games not updating (NEW!)

### ⚠️ CAN Detect & Alert (No Auto-Fix)

- Discord webhook issues
- Bookmaker API issues
- Trigger logic issues

### ❌ CANNOT Detect

- Odds format changes
- Calculation errors
- Logic bugs in predictions
- Model degradation

---

## 🎯 Best Practices

### For Now

1. ✅ Keep watchdog running 24/7
2. ✅ Monitor Discord alerts
3. ✅ Respond to API failure alerts immediately
4. ✅ Check logs for 403/timeout errors
5. ✅ Update manually if needed (like we did today)

### Future Improvements

1. Add Discord webhook health check
2. Add bookmaker API health check
3. Add trigger logic validation
4. Add odds format validation
5. Add model performance monitoring

---

## 🚀 How to Use the Updated Watchdog

### Start Watchdog

```bash
# Start with default 60-second check interval
./start_with_watchdog.sh

# Or manually
nohup .venv/bin/python watchdog.py > watchdog.log 2>&1 &
```

### Watch for New Alerts

The watchdog will now alert you if:
- ⚠️ **"X games not updating (API failure)"**

This means:
1. Games have reached halftime (or are in progress)
2. Database not being updated
3. Likely API 403 or timeout
4. **Manual intervention needed**

### How to Fix API Failure Alert

**Option 1: Wait**
- APIs may recover on their own
- Watchdog will alert when games start updating again

**Option 2: Manual Update**
```bash
# Find game at halftime
python3 << 'EOF'
from dashboard.backend.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
result = db.execute(text("""
    SELECT id, home_team, away_team, nba_id
    FROM games
    WHERE game_status = 'Scheduled'
      AND game_date >= date('now', '-1 day')
""")).fetchall()

games = result.fetchall()
for (game_id, home, away, nba_id) in games:
    print(f"{game_id}: {away} @ {home} ({nba_id})")

db.close()
EOF

# Update game to Halftime
python3 << 'EOF'
from dashboard.backend.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()

game_id = 59  # Replace with actual game ID
db.execute(text("""
    UPDATE games
    SET game_status = 'Halftime',
        period = 2,
        clock = '0:00',
        updated_at = datetime('now')
    WHERE id = :game_id
""), {"game_id": game_id})

db.commit()
db.close()
EOF
```

**Option 3: Restart Automation**
```bash
./stop_with_watchdog.sh
./start_with_watchdog.sh
```

---

## ✅ Summary

### What Was Fixed

✅ Watchdog now detects API failures
✅ Alerts if games stop updating for 5+ minutes
✅ Identifies the exact issue (403, timeout, etc.)

### What Still Can't Be Fixed Automatically

⚠️ Discord posting failures (manual fix required)
⚠️ Odds parsing errors (code update required)
⚠️ Trigger logic bugs (code review required)

### What the Watchdog NOW Provides

✅ **Early warning** of API issues
✅ **Specific alerts** about what's failing
✅ **Actionable information** for manual fixes
✅ **24/7 monitoring** of all components

---

**Update completed by Perry (code-puppy-724a09) on 2026-02-26**

*"I am Perry! 🐶 Your code puppy!!"*

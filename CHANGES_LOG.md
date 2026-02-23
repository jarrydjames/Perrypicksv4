# PerryPicks v4 - Bug Fixes and Reliability Improvements

## 2026-02-21: Quality of Life Improvements

### New Files Created

#### 1. `src/automation/channel_router.py`
Multi-channel Discord routing system for different alert types:
- **MAIN channel**: Standard halftime predictions
- **HIGH_CONFIDENCE channel**: Predictions with tier A or >65% confidence
- **SGP channel**: Same Game Parlay suggestions when 2+ high-confidence picks exist
- **ALERTS channel**: System notifications

**Usage:**
```python
from src.automation.channel_router import ChannelRouter

router = ChannelRouter(
    main_webhook=os.environ.get("DISCORD_WEBHOOK_URL"),
    high_confidence_webhook=os.environ.get("DISCORD_HIGH_CONFIDENCE_WEBHOOK"),
)
results = router.route_prediction(content, prediction, recommendations)
```

**Environment Variables:**
- `DISCORD_WEBHOOK_URL`: Main channel
- `DISCORD_HIGH_CONFIDENCE_WEBHOOK`: High confidence alerts
- `DISCORD_SGP_WEBHOOK`: SGP suggestions
- `DISCORD_ALERTS_WEBHOOK`: System alerts

---

#### 2. `src/automation/brand_voice.py`
Branded content generation with consistent voice and formatting:
- Consistent emoji usage and formatting
- Perry persona voice ("Here's the breakdown:", "Trust the model")
- Confidence tier labels (STRONG PLAY, SOLID PLAY, etc.)
- SGP formatting
- High confidence alert formatting

**Usage:**
```python
from src.automation.brand_voice import BrandVoice

brand = BrandVoice()
content = brand.format_halftime_post(
    away_tricode="BOS",
    home_tricode="LAL",
    h1_away=55,
    h1_home=58,
    prediction=prediction,
    recommendations=recommendations,
)
```

---

#### 3. `src/automation/health_monitor.py`
System health monitoring and alerting:
- NBA CDN API health check
- Local Odds API health check
- Discord webhook validation
- REPTAR model status
- Database connectivity

**Usage:**
```python
from src.automation.health_monitor import HealthMonitor

monitor = HealthMonitor(discord_alert_callback=send_alert)
status = monitor.check_all()
if not status.healthy:
    monitor.send_alert(status)
```

---

### Configuration for Multi-Channel Setup

To enable multi-channel posting, add these environment variables:

```bash
# Main predictions (required)
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# Optional: High confidence alerts (tier A or >65%)
DISCORD_HIGH_CONFIDENCE_WEBHOOK=https://discord.com/api/webhooks/...

# Optional: Same Game Parlays
DISCORD_SGP_WEBHOOK=https://discord.com/api/webhooks/...

# Optional: System alerts
DISCORD_ALERTS_WEBHOOK=https://discord.com/api/webhooks/...
```

---

## 2026-02-21: Critical Bug Fixes for Autonomous Operation

### Summary
Fixed 19+ critical bugs identified by code review agents that would prevent autonomous operation for days on end.

---

## File Changes

### 1. `src/models/reptar_predictor.py`

**Fix 1: NaN Prediction Validation (Lines 316-322)**
- **Issue**: Model could return NaN/Inf predictions without detection, causing invalid data to be posted to Discord
- **Fix**: Added validation to check `np.isfinite()` on predictions, raises ValueError if invalid
- **Rollback**: Remove the NaN validation block after `pred_2h_margin` assignment

**Fix 2: Division by Zero Protection (Lines 332-334)**
- **Issue**: `norm.cdf()` with `sigma=0` causes division by zero crash
- **Fix**: Added `sigma_margin_safe = max(self._sigma_margin, 0.1)` guard
- **Rollback**: Replace with original `scale=self._sigma_margin`

**Fix 3: Feature Validation Enforcement (Lines 308-310)**
- **Issue**: Feature validation only logged warnings, continued with invalid predictions
- **Fix**: Changed to raise ValueError on validation failure
- **Rollback**: Change `logger.error` + `raise` back to `logger.warning`

**Fix 4: Missing Margin Features Fill (Lines 303-305)**
- **Issue**: Only filled missing features for `_total_features`, not `_margin_features`, causing KeyError
- **Fix**: Loop over `self._total_features + self._margin_features`
- **Rollback**: Change back to loop over only `self._total_features`

**Fix 5: Box Score Null Check (Lines 393-397)**
- **Issue**: No validation that fetched box score has required data
- **Fix**: Added check for `box`, `homeTeam`, and `awayTeam` keys
- **Rollback**: Remove the validation block after `fetch_box(game_id)`

**Fix 6: Timezone Handling (Lines 483-486)**
- **Issue**: Timezone-aware datetimes weren't converted to UTC
- **Fix**: Added `tz_convert('UTC')` for already-timezone-aware datetimes
- **Rollback**: Remove the `else: target_dt = target_dt.tz_convert('UTC')` branch

---

### 2. `src/features/temporal_store.py`

**Fix 1: Missing Column Check (Lines 222-228)**
- **Issue**: `get_team_features()` didn't validate `game_date` column exists before filtering
- **Fix**: Added check for column existence with early return
- **Rollback**: Remove the column validation block

---

### 3. `src/data/game_data.py`

**Fix 1: Timeout/SSL Exception Handling (Lines 129-149)**
- **Issue**: Timeout, ConnectionError, and SSLError exceptions weren't caught, causing crashes
- **Fix**: Added except block for these exceptions with retry logic
- **Rollback**: Remove the `except (requests.Timeout, ...)` block

**Fix 2: Corrupt Cache Cleanup (Lines 91-97)**
- **Issue**: Corrupt cache files were never deleted, wasting time on every request
- **Fix**: Added `json.JSONDecodeError` handling that deletes corrupt files
- **Rollback**: Remove the `except json.JSONDecodeError:` block

**Fix 3: Reduced Cache TTL (Line 37)**
- **Issue**: 5-minute cache was too long for live game data at halftime
- **Fix**: Changed `CACHE_TTL_SECONDS` from 300 to 30
- **Rollback**: Change back to `CACHE_TTL_SECONDS = 300`

**Fix 4: API Response Validation (Lines 172-176)**
- **Issue**: No validation that API response contains expected 'game' key
- **Fix**: Added check for 'game' key with informative error message
- **Rollback**: Remove the `if "game" not in data:` block

**Fix 5: Period Score Robustness (Lines 195-220)**
- **Issue**: Could use cumulative 'score' instead of period-specific points
- **Fix**: Reordered key priority to prefer 'points', 'pts', 'periodScore' over 'score', added sanity check
- **Rollback**: Change key order back to `("score", "points", "pts")` and remove sanity check

**Fix 6: Connection Pool for Concurrency (Lines 28-46)**
- **Issue**: No connection pool configured, could exhaust connections with 10+ concurrent games
- **Fix**: Added requests.Session with HTTPAdapter (pool_connections=20, pool_maxsize=20)
- **Rollback**: Remove the session/pool configuration and use `requests.get` directly

---

### 4. `src/automation/discord_client.py`

**Fix 1: Rate Limit Header Parsing (Lines 351-361)**
- **Issue**: `float(retry_after)` could crash on malformed header
- **Fix**: Wrapped in try/except with fallback to exponential backoff
- **Rollback**: Replace with original `delay = float(retry_after) if retry_after else ...`

**Fix 2: JSON Response Parsing (Lines 343-351)**
- **Issue**: `response.json()` could raise ValueError on invalid JSON
- **Fix**: Wrapped in try/except, retries on parse failure
- **Rollback**: Remove the try/except around `response.json()`

**Fix 3: Increased Timeout (Line 335)**
- **Issue**: 10-second timeout too short for unreliable networks
- **Fix**: Changed timeout from 10 to 30 seconds
- **Rollback**: Change back to `timeout=10`

**Fix 4: Transient 4xx Retry (Lines 371-373)**
- **Issue**: Some 4xx errors (400, 408) may be transient but weren't retried
- **Fix**: Added retry for status codes 400 and 408
- **Rollback**: Remove the `if response.status_code in (400, 408):` block

---

### 5. `src/odds/odds_api.py`

**Fix 1: Retry Logic for External API (Lines 172-200)**
- **Issue**: No retry on transient network failures or rate limits
- **Fix**: Added 3-attempt retry loop with exponential backoff
- **Rollback**: Remove the `for attempt in range(max_retries):` loop

**Fix 2: Added Time Import (Line 4)**
- **Issue**: `time` module not imported but needed for retry delays
- **Fix**: Added `import time`
- **Rollback**: Remove `import time`

**Fix 3: Timeout Consistency (Line 106)**
- **Issue**: External API timeout was 10s vs local API's 45s
- **Fix**: Increased default timeout from 10 to 45 seconds
- **Rollback**: Change back to `timeout_s: int = 10`

---

### 6. `src/automation/service.py`

**Fix 1: None-Safe Logging (Lines 295-299)**
- **Issue**: Odds values could be None, showing confusing "None" in logs
- **Fix**: Added `or 'N/A'` fallback for display
- **Rollback**: Remove the `or 'N/A'` fallbacks

---

### 7. `start.py`

**Fix 1: ESPN Fallback Validation (Lines 873-900)**
- **Issue**: ESPN fallback didn't validate odds before using
- **Fix**: Added check for valid total_points or spread_home, skip if both None
- **Rollback**: Remove the validation block and restore original structure

**Fix 2: Database Status Update on Discord Post (Lines 951-970)**
- **Issue**: Prediction database status never updated after Discord posting attempt
- **Fix**: Added database update after Discord post with POSTED or FAILED status
- **Rollback**: Remove the database update block after `_post_to_discord`

**Fix 3: Return Discord Result (Lines 1237-1245)**
- **Issue**: `_post_to_discord` didn't return result, caller couldn't know if post succeeded
- **Fix**: Return the DiscordPostResult (or None on exception)
- **Rollback**: Remove the `return result` and `return None` statements

**Fix 4: Odds API Health Check Enforcement (Lines 258-276)**
- **Issue**: System would set USE_LOCAL_ODDS_API=true even if health check failed
- **Fix**: Explicitly set USE_LOCAL_ODDS_API=false if health check fails, changed warning to error
- **Rollback**: Change error back to warning, remove the `os.environ["USE_LOCAL_ODDS_API"] = "false"` line

---

### 8. `dashboard/backend/database.py`

**Fix 1: Added PredictionStatus Values (Lines 31-36)**
- **Issue**: No status for tracking Discord posting success/failure
- **Fix**: Added POSTED and FAILED to PredictionStatus enum
- **Rollback**: Remove POSTED and FAILED from enum

---

## Remaining Known Issues

1. **Race condition in global predictor singleton** - Low priority, unlikely to cause issues at current scale
2. **Memory leak in feature store** - Low priority, not significant at current data size
3. **No webhook URL validation beyond prefix** - Would need regex validation
4. **Message truncation loses data** - Consider splitting long messages

---

## Testing Recommendations

1. Run `pytest tests/` to verify no regressions
2. Test with `python -m src.models.reptar_predictor` using a known game ID
3. Monitor first few hours of automated operation
4. Check logs for any new warnings

---

## Rollback Procedure

To rollback a specific fix:
1. Locate the fix in this document
2. Find the file and line numbers
3. Apply the rollback instruction
4. Test the change

To rollback all changes:
```bash
git checkout HEAD -- src/models/reptar_predictor.py
git checkout HEAD -- src/data/game_data.py
git checkout HEAD -- src/automation/discord_client.py
git checkout HEAD -- src/odds/odds_api.py
git checkout HEAD -- src/automation/service.py
git checkout HEAD -- start.py
```

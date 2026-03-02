# Context Reference Master

**For PerryPicks v4 - Persistent Knowledge Base**

**Version**: 1.4.0  
**Created**: 2026-02-26  
**Last Updated**: 2026-02-28 (Session: Odds API Fixes & Architecture)  
**Author**: Perry (code-puppy-724a09)

---

## 🎯 Purpose

This is a **persistent context library** for PerryPicks. When encountering any issue:

1. **Check this reference FIRST**
2. Look up the error/issue
3. Follow the documented fix
4. Only then consider new solutions


This ensures we don't repeat the same troubleshooting steps and captures all learned knowledge.

---

## 📋 System Overview

### Architecture

```
Automation Service (start.py) - Main daemon
├── Game State Monitor - Polls NBA CDN every 30s
├── Trigger Engine - Detects halftime, Q3 5min
├── Prediction Generator - Creates betting recommendations
├── Discord Bot - Posts predictions
└── Health Watchdog - Monitors all components


Dashboard API - Web interface
Odds API - Fetches live betting odds
```

### Data Flow

1. Schedule fetched from ESPN/NBA CDN
2. Games stored in SQLite database
3. MAXIMUS (pregame) cycle periodically creates pregame predictions (DB-backed, idempotent)
4. Game State Monitor polls NBA CDN every 30s
5. When game reaches halftime/Q3-5min, trigger fires
6. Prediction generated using REPTAR model
7. Live odds fetched from bookmakers
8. Recommendations created (spread, total, ML props)
9. Prediction posted to Discord

---

## 📁 Critical Files

| File | Purpose | Key Functions |
------|---------|-------------|
| **start.py** | Main automation daemon | `_update_game_statuses()`, `_run_halftime_trigger()`, `_run_q3_5min_trigger()` |
| **watchdog.py** | Health monitoring | `_check_automation()`, `_check_stuck_states()`, `_restart_automation()` |
| **dashboard/backend/database.py** | ORM models | Tables: games, predictions, ghost_bets |
| **src/automation/game_state.py** | Live game updates | `update_all_games()`, `get_live_games()` |
| **src/discord_bot/prediction_generator.py** | Bet recommendations | `generate_halftime_post()`, `_calculate_edge()`, `_confidence_tier()` |
| **src/discord_bot/discord_bot.py** | Discord posting | `send_discord_message()` |
| **src/schedule.py** | Game schedules | `fetch_schedule()`, `get_nba_ids()` |
| **src/automation/pregame_cycle.py** | MAXIMUS pregame generator | `run_pregame_cycle()` |
| **src/automation/maximus_pregame_poster.py** | MAXIMUS pregame Discord posting | `post_pending()` |
| **src/data/pregame_features.py** | MAXIMUS feature contract | `build_pregame_features()` |

---

## 🗄 Database Schema

### games table

- **id** (PK) - Internal ID
- **nba_id** - NBA game ID (e.g., 0022500855)
- **home_team** - Tricode (PHX, LAL)
- **away_team** - Tricode (LAL, PHX)
- **game_status** - Scheduled, In Progress, Halftime, Final
- **period** - Current quarter (1-4, 5+ for OT)
- **clock** - Game clock (e.g., '7:42')
- **updated_at** - When game was last updated

**Critical**: Trigger checks `game_status`, `period`, `clock`

### predictions table

- **id** (PK) - Prediction ID
- **game_id** (FK) - Links to games table
- **trigger_type** - pregame, halftime, q3_5min
- **status** - pending, posted, failed, correct, wrong
- **posted_to_discord** - Boolean
- **created_at** - Timestamp

**Critical**: Watchdog checks for stale predictions (>4h old, not posted)

---

## 🔑 Environment Variables

| Variable | Purpose | Required | Default |
----------|---------|----------|----------|
| **DISCORD_WEBHOOK_URL** | Discord webhook for REPTAR (halftime/Q3) predictions | Yes | - |
| **DISCORD_ALERTS_WEBHOOK** | Discord webhook for alerts | No | Falls back to DISCORD_WEBHOOK_URL |
| **DISCORD_MAXIMUS_PREGAME_WEBHOOK** | Discord webhook for MAXIMUS pregame posts | Only if posting enabled | - |
| **USE_LOCAL_ODDS_API** | Use local odds API | No | false |
| **ODDS_API_BASE_URL** | Local odds API base URL (when USE_LOCAL_ODDS_API=true) | No | http://localhost:8890 |
| **MAXIMUS_PREGAME_ENABLED** | Enable MAXIMUS pregame cycle | No | true |
| **MAXIMUS_PREGAME_INTERVAL_MIN** | How often to run pregame cycle | No | 10 |
| **MAXIMUS_PREGAME_LOOKAHEAD_HOURS** | Lookahead window for upcoming games | No | 12 |
| **MAXIMUS_PREGAME_MIN_MINUTES_BEFORE_TIP** | Minimum minutes before tip to create prediction | No | 15 |
| **MAXIMUS_PREGAME_POSTING_ENABLED** | Enable MAXIMUS pregame Discord posting | No | false |
| **MAXIMUS_PREGAME_POSTING_INTERVAL_S** | How often to try posting pending pregame predictions | No | 120 |
| **MAXIMUS_PREGAME_POST_MIN_MINUTES_BEFORE_TIP** | Only post if tip is at least N minutes away | No | 10 |
| **DATABASE_URL** | SQLite database path | No | sqlite:///dashboard/backend/perrypicks.db |

---

## 🧭 Discord Channel Routing (REPTAR + MAXIMUS)

Routing is handled by `src/automation/channel_router.py`.

### Channels
- **MAIN**: Default channel for a post
- **HIGH_CONFIDENCE**: “Priority bucket” (tier A or prob ≥ 72% by default)
- **SGP**: Same Game Parlay channel (when multiple legs qualify)

### MAXIMUS pregame routing
- Posts go to **DISCORD_MAXIMUS_PREGAME_WEBHOOK** (MAIN) by default.
- If any recommendation qualifies as **HIGH_CONFIDENCE**, it also posts to the priority channel.
  - Threshold is configurable via `PRIORITY_PROB_THRESHOLD` (default 0.72)
- If SGP conditions are met, it also posts the SGP message to the parlay channel and saves parlay tracking.

### SGP / parlay correlation rules (related markets)
SGP leg selection enforces:
- ❌ **No ML + Spread** for the same game (related markets)
- ❌ **No Game Total + Both Team Totals** (related markets)
  - If a game total is included, allow **at most 1** team total.

---

## 📊 Odds API Architecture

### Composite Provider

The odds API uses a **composite provider** that automatically switches between two data sources based on game state:

#### PREGAME Odds (ESPN API)
- **Source**: ESPN API (free, reliable)
- **Coverage**: All NBA games
- **Markets**: Moneyline, Spread, Total, Team Totals
- **Latency**: ~3 seconds to fetch
- **Used when**: Game is scheduled or before tip-off

#### LIVE/HALFTIME Odds (DraftKings Live)
- **Source**: DraftKings Live website (browser automation via Playwright)
- **Coverage**: Live games only
- **Markets**: Moneyline, Spread, Total (Team Totals derived when needed)
- **Latency**: ~20 seconds to fetch (browser automation overhead)
- **Used when**: Game is in progress or at halftime

#### Composite Logic
```
IF game is PREGAME:
    → Fetch from ESPN API
    → Fast, reliable, free
    → All markets available

IF game is LIVE/HALFTIME:
    → Fetch from DraftKings Live
    → Requires browser automation
    → Slower (20s), but live data
    → Team totals derived if not provided
```

### Startup Time
The composite provider waits for BOTH sources to complete:
- ESPN: ~3 seconds
- DraftKings Live: ~20 seconds
- **Total: ~25 seconds**

**This is why automation waits 25 seconds before checking health endpoint**

### Derived Team Totals

When DraftKings Live doesn't provide team totals (common), they are automatically derived:

```python
# Formula
derived_home_total = (total_points - spread_home) / 2
derived_away_total = (total_points + spread_home) / 2

# Example
total_points = 230
spread_home = -5.5  # Home favored

derived_home = (230 - (-5.5)) / 2 = 117.75  # Home scores more
derived_away = (230 + (-5.5)) / 2 = 112.25  # Away scores less
```

### API Endpoints

#### Health Check
```bash
GET http://localhost:8890/v1/health
Returns: {"status": "healthy", "uptime_seconds": X, "upstreams": [...]}
```

#### All Odds
```bash
GET http://localhost:8890/v1/odds?sport=nba
Returns: All NBA games with odds from both sources
```

#### Snapshot (Single Game)
```bash
GET http://localhost:8890/v1/snapshot?home_name=<team>&away_name=<team>
Returns: Single game snapshot with all markets
```

### Response Format
```json
{
    "home_team": "Miami Heat",
    "away_team": "Houston Rockets",
    "home_tricode": "MIA",
    "away_tricode": "HOU",
    "snapshot": {
        "total_points": 226.5,
        "total_over_odds": -108,
        "total_under_odds": -112,
        "spread_home": 1.5,
        "spread_home_odds": -110,
        "spread_away_odds": -110,
        "moneyline_home": 110,
        "moneyline_away": -130,
        "team_total_home": null,  // May be provided or null
        "team_total_home_over_odds": null,
        "team_total_home_under_odds": null,
        "team_total_away": null,
        "team_total_away_over_odds": null,
        "team_total_away_under_odds": null,
        "derived_team_total_home": 112.5,  // Calculated if null
        "derived_team_total_away": 114.0,  // Calculated if null
        "bookmaker": "Draft Kings",  // "ESPN" or "Draft Kings"
        "last_update": "2026-02-28T19:30:36.791207Z"
    },
    "found": true
}
```

### Critical Notes

1. **DraftKings Live is SLOW**: Browser automation takes 20+ seconds
   - Automation MUST wait 25+ seconds before health checks
   - See Issue #10: Odds API Startup Timing Failure

2. **Zombie Processes Break Everything**: Old odds API processes must be killed
   - Port 8890 cannot be reused
   - See Issue #9: Odds API Zombie Process

3. **Team Totals Often Null**: Bookmakers don't always provide them
   - System automatically derives them from total + spread
   - Derived totals are mathematically accurate

4. **Bookmaker Field Shows Source**: 
   - "ESPN" = pregame odds
   - "Draft Kings" = live odds
   - Helps identify which source was used

5. **No Rate Limits**: ESPN and DraftKings have no strict rate limits
   - Composite provider polls regularly (every 90 seconds)
   - Cache TTL is 85 seconds
   - Stale max is 300 seconds

### Configuration

The odds API is configured via environment variables in `start.py`:

```python
# Enable local odds API
os.environ["USE_LOCAL_ODDS_API"] = "true"
os.environ["ODDS_API_BASE_URL"] = "http://localhost:8890"

# Composite provider (automatically switches)
os.environ["ODDS_PROVIDER"] = "composite"
```

### Code Locations

- **Odds API Server**: `/Users/jarrydhawley/Desktop/Predictor/Odds_Api/app/main.py`
- **Composite Adapter**: `/Users/jarrydhawley/Desktop/Predictor/Odds_Api/app/adapters/composite_adapter.py`
- **ESPN Adapter**: `/Users/jarrydhawley/Desktop/Predictor/Odds_Api/app/adapters/espn_adapter.py`
- **DraftKings Live Adapter**: `/Users/jarrydhawley/Desktop/Predictor/Odds_Api/app/adapters/draftkings_live_adapter.py`
- **PerryPicks Client**: `/Users/jarrydhawley/Desktop/Predictor/PerryPicks_v4/src/odds/local_odds_client.py`

---

---

## ⚠️ Common Errors & Solutions

### 1. Game Not Updating (API Failure)

**Symptoms**:
- Game at halftime but no prediction posted
- Database shows "Scheduled" when game is live
- Logs show "403 Forbidden" from NBA CDN
- Logs show "timeout" from ESPN


**Root Cause**:
- NBA CDN rate limiting (403 Forbidden)
- ESPN API connectivity issues (timeout)
- Network issues

**Detection**:
- Watchdog: "X games not updating (API failure)"

**Immediate Fix**:
```sql
-- 1. Find game ID
SELECT id, home_team, away_team FROM games WHERE home_team = 'PHX';

-- 2. Update game status
UPDATE games
SET game_status = 'Halftime', period = 2, clock = '0:00', updated_at = datetime('now')
WHERE id = <game_id>;

-- 3. Wait 10 seconds for trigger
-- 4. Check if prediction created
SELECT * FROM predictions WHERE game_id = <game_id> AND trigger_type = 'halftime';
```

**Long-term Fix**:
- Reduce NBA CDN polling frequency
- Add retry logic with exponential backoff
- Use ESPN as fallback for live data

---

### 2. Trigger Not Firing

**Symptoms**:
- Game at halftime but no prediction created
- Trigger logic should have fired but didn't
- Game status updated correctly but no prediction

**Root Cause**:
- Trigger not checking correct status value
- Trigger not being called at all
- Trigger disabled in configuration
- Bug in trigger logic

**Detection**:
- Watchdog CANNOT detect this (logic bug)

**Troubleshooting Steps**:
1. Check trigger configuration in start.py
2. Check if trigger is enabled
3. Check game status in database
4. Check logs for trigger activity
5. Manually trigger prediction to test

```bash
# Manual trigger test
python3 -c "from src.discord_bot.prediction_generator import generate_halftime_post; generate_halftime_post(<game_id>)"
```

---

### 3. Odds Fetch Failure

**Symptoms**:
- Prediction created but has no odds
- Bets show "Odds: N/A"
- Logs show timeout or connection errors from odds API

**Root Cause**:
- Odds API not responding
- Bookmaker API rate limiting
- Network issues
- Invalid game ID

**Detection**:
- Watchdog CANNOT detect (HTTP 200 OK, but no data)

**Immediate Fix**:
1. Check odds API status: `curl http://localhost:8890/v1/health`
2. Check logs for error messages
3. Retry manually
4. Use different bookmaker API

**Retry Logic** (Already Implemented):
- Attempts: 8
- Backoff: Exponential
- Total time: 8 minutes
- Code location: `src/discord_bot/prediction_generator.py`

---

### 4. Discord Posting Failure

**Symptoms**:
- Prediction created but not posted
- Logs show prediction generated
- Database shows `posted_to_discord = False`
- No Discord message received

**Root Cause**:
- Invalid webhook URL
- Discord webhook deleted/expired
- Discord rate limiting
- Webhook permissions issue
- Network issues

**Detection**:
- Watchdog: "stale predictions (>4 hours old, not posted)"

**Immediate Fix**:
```bash
# 1. Verify webhook URL in .env
cat .env | grep DISCORD

# 2. Test webhook manually
curl -X POST -H 'Content-Type: application/json' \
  -d '{"content": "Test from Perry"}' \
  <WEBHOOK_URL>

# 3. Check Discord for message
# 4. If error: update webhook URL and restart
```

---

### 5. Team Matching Failure

**Symptoms**:
- Prediction missing teams
- "Team: None" in post
- Bets for wrong teams

**Root Cause**:
- Team tricodes don't match
- Team names don't match
- Nickname vs city name mismatch

**Detection**:
- Visual inspection of Discord posts

**Immediate Fix**:
1. Check team tricodes in database
2. Check team tricodes from NBA CDN
3. Update team mapping in code
4. Use tricode-first matching (implemented)

**Current Logic** (Already Implemented):
- Priority: Tricode → City → Name
- Tricodes: BOS, LAL, GSW, etc.
- Fallback: Try city/name if tricode fails
- Code location: `src/discord_bot/prediction_generator.py`

---

### 6. Low Confidence Bets

**Symptoms**:
- Bets with 55-60% confidence being posted
- User feedback: too many low-confidence bets

**Root Cause**:
- Confidence threshold too low
- Minimum confidence not enforced

**Detection**:
- User reports / manual review

**Current Thresholds** (Already Implemented):
- A-Tier: 80%+ confidence
- B-Tier: 75-79% confidence
- C-Tier: 70-74% confidence
- Below 70%: Not posted

**Code location**: `src/discord_bot/prediction_generator.py`

---

### 7. Memory Issues

**Symptoms**:
- System slow
- Process killed
- Watchdog: "Memory: Critical (>90%)"

**Root Cause**:
- Reptar model not being unloaded
- Memory leak
- Too many cached games
- Too many open database connections

**Detection**:
- Watchdog memory check

**Immediate Fix**:
1. Restart automation
2. Clear cache
3. Close unused database connections
4. Increase system memory

**Code locations**:
- Reptar loading: `src/reptar_integration.py`
- Cache: `src/data/game_data.py`

---

### 8. Team Total Odds Flipped

**Symptoms**:
- Team total bets assigned to wrong team
- Home team total recommendations showing for away team
- Away team total recommendations showing for home team
- Betting recommendations for team totals are incorrect

**Root Cause**:
- Team total derivation formula in `start.py` was flipped
- Formula: `Home = (Total + Spread) / 2, Away = (Total - Spread) / 2`
- Should be: `Home = (Total - Spread) / 2, Away = (Total + Spread) / 2`
- Spread is negative when home is favored

**Example**:
```
Total: 230, Spread: -5.5 (home favored)
Old (buggy):  Home = (230 + (-5.5)) / 2 = 112.25 ❌
              Away = (230 - (-5.5)) / 2 = 117.75 ❌
New (fixed):  Home = (230 - (-5.5)) / 2 = 117.75 ✅ (home scores more)
              Away = (230 + (-5.5)) / 2 = 112.25 ✅ (away scores less)
```

**Detection**:
- Visual inspection of Discord posts
- Compare predicted team totals with spread
- If home is favored (negative spread), home team total should be higher

**Immediate Fix**:
1. Fixed in `start.py` line ~1800
2. Changed: `derived_home = (total + spread) / 2.0`
3. Changed: `derived_away = (total - spread) / 2.0`
4. To: `derived_home = (total - spread) / 2.0`
5. To: `derived_away = (total + spread) / 2.0`
6. Restart automation

**Code location**: `start.py` - `_generate_recommendations_from_snapshot()` method
**Fixed date**: 2026-02-27
**Important note**: This affects ONLY derived team totals (when bookmaker doesn't provide them). Team totals directly from bookmaker are not affected.



---

### 9. Odds API Zombie Process (CRITICAL)

**Symptoms**:
- Prediction posts created WITHOUT odds/recommendations
- Logs show "No odds match found" or 404 errors
- Odds API port 8890 appears to be in use
- System fell back to external API (not configured)

**Root Cause**:
- Old odds API process from previous session still running on port 8890
- New automation cannot start fresh odds API server
- All odds API calls return 404 errors
- Result: Posts go out without betting recommendations

**Detection**:
- Visual inspection of Discord posts (no recommendations)
- Check port: `lsof -i :8890` shows process not owned by current automation
- Check logs: `Odds fetch error: No odds match found`

**Immediate Fix**:
```bash
# 1. Find the zombie process
lsof -i :8890
ps aux | grep 8890

# 2. Kill the zombie process
kill -9 <PID>

# 3. Verify port is free
lsof -i :8890

# 4. Restart automation
pkill -f "python start.py"
cd /Users/jarrydhawley/Desktop/Predictor/PerryPicks_v4
source .venv/bin/activate
nohup python start.py > automation.log 2>&1 &

# 5. Wait 30 seconds for startup
# 6. Verify odds API started
curl http://localhost:8890/v1/health
```

**Long-term Fix**:
- Automation startup should check for existing processes
- Kill any existing odds API processes before starting new ones
- Add port binding check before starting odds API

**Code location**: `start.py` - `_start_odds_api()` method
**Fixed date**: 2026-02-28

---

### 10. Odds API Startup Timing Failure (CRITICAL)

**Symptoms**:
- Automation shows "Odds API failed to start"
- Logs show health check failures
- System falls back to external API (not configured)
- Posts created without odds

**Root Cause**:
- Automation waits only 3 seconds before checking health endpoint
- DraftKings Live adapter takes 20+ seconds to fetch odds and complete startup
- Health check attempted 15 times (1-second intervals)
- All health checks fail before API is ready
- Result: System assumes API failed and falls back

**Detection**:
- Check logs: "Odds API failed to start after 15 attempts"
- Manual health check after startup: `curl http://localhost:8890/v1/health` - should work

**Immediate Fix**:
```python
# In start.py, modify _start_odds_api() method:

# Line ~433 - Increase initial wait time
# OLD: time.sleep(3)
# NEW: time.sleep(25)

# Line ~441 - Increase retry attempts
# OLD: for attempt in range(15):
# NEW: for attempt in range(30):
```

**Explanation**:
- DraftKings Live adapter requires browser automation
- Browser startup takes ~20 seconds to fetch live odds
- ESPN pre-game odds are fast (~3 seconds)
- Composite provider waits for both to complete
- 25 seconds gives enough time for both to finish

**Restart Procedure**:
1. Kill automation: `pkill -f "python start.py"`
2. Kill any odds API processes: `pkill -f "uvicorn"`
3. Start automation: `nohup python start.py > automation.log 2>&1 &`
4. Wait 30-35 seconds for startup
5. Verify health: `curl http://localhost:8890/v1/health`

**Expected Startup Log**:
```
2026-02-28 13:26:54 [INFO] PerryPicks: Starting local Odds API on port 8890...
[... 25 second wait ...]
2026-02-28 13:27:19 [INFO] PerryPicks: Odds API ready at http://localhost:8890
```

**Code location**: `start.py` - `_start_odds_api()` method (lines 397-444)
**Fixed date**: 2026-02-28
**Important note**: This is necessary because DraftKings Live uses browser automation (Playwright) which is slower than simple API calls.

---



---

### 11. DraftKings Live Parsing Failure (CRITICAL)

**Symptoms**:
- DraftKings Live adapter returns 0 games
- Live games visible on website but not in API
- Logs show: `draftkings_live_complete games_count=0`
- No errors during fetch, just no results

**Root Cause**:
- DraftKings changed their page structure
- Parser uses outdated regex patterns
- Current parser looks for: `^[A-Z]{2,3}\s+\w+$` (e.g., "ATL Hawks")
- Actual format: `POR Trail Blazers-logo POR Trail Blazers 55 at CHA Hornets-logo CHA Hornets 67 +12.5 −115`
- Page structure changed, parsing logic is broken

**Detection**:
- Check logs: `draftkings_live_complete games_count=0`
- Manual check: Games visible on https://sportsbook.draftkings.com/live
- Test adapter directly (returns empty list)

**Immediate Fix**:
**NONE AVAILABLE** - Parser needs to be rewritten to match new page structure

**Workaround**:
- Use ESPN for pregame odds only
- Live odds unavailable until parser is fixed
- Manual odds entry for critical games

**Long-term Fix**:
1. Analyze current DraftKings Live page structure
2. Update `_parse_games()` method in `/Predictor/Odds_Api/app/adapters/draftkings_live_adapter.py`
3. Update regex patterns to match new format
4. Test with current live games
5. Deploy updated adapter

**Code location**: `/Predictor/Odds_Api/app/adapters/draftkings_live_adapter.py` - `_parse_games()` method
**Status**: BROKEN as of 2026-02-28
**Impact**: Live halftime predictions cannot fetch live odds

**Important note**: This is a parsing issue, not a rate limit or blocking issue. The page loads successfully, but the parser can't extract game data.

---

---

## 🔄 Critical Processes

### Main Automation
- **Name**: Automation Service
- **PID File**: `.perrypicks.pid`
- **Start Command**: `python start.py`
- **Start Script**: `./start_with_watchdog.sh`
- **Stop Command**: `kill -15 $(cat .perrypicks.pid)`
- **Check Running**: `ps -p $(cat .perrypicks.pid)`
- **IMPORTANT**: MUST be running for system to work


### Health Watchdog
- **Name**: Health Watchdog
- **PID File**: `.watchdog.pid`
- **Start Command**: `python watchdog.py`
- **Start Script**: `./start_with_watchdog.sh`
- **Stop Command**: `kill -15 $(cat .watchdog.pid)`
- **Check Running**: `ps -p $(cat .watchdog.pid)`
- **IMPORTANT**: Should run independently of automation


### Dashboard Backend
- **Name**: Dashboard Backend
- **Port**: 8000
- **Health Endpoint**: `/api/health`
- **Start**: Starts with automation
- **IMPORTANT**: Provides web interface


### Odds API
- **Name**: Odds API
- **Port**: 8890
- **Health Endpoint**: `/v1/health`
- **Env Var**: `USE_LOCAL_ODDS_API`
- **IMPORTANT**: Fetches live betting odds

---

## 📊 Database Queries

### Get Today's Games
```sql
SELECT * FROM games WHERE DATE(game_date) = DATE('now');
```

### Get Games at Halftime
```sql
SELECT * FROM games 
WHERE game_status = 'Halftime' 
   OR (period = 2 AND game_status LIKE '%Halftime%');
```

### Get Recent Predictions
```sql
SELECT * FROM predictions 
WHERE created_at > datetime('now', '-1 hour') 
ORDER BY created_at DESC;
```

### Get Stale Predictions
```sql
SELECT * FROM predictions 
WHERE created_at < datetime('now', '-4 hours') 
  AND posted_to_discord = 0;
```

### Get Games Not Updating
```sql
SELECT * FROM games 
WHERE DATE(game_date) = DATE('now') 
  AND (updated_at IS NULL OR updated_at < datetime('now', '-5 minutes')) 
  AND game_status NOT IN ('Final', 'Scheduled');
```

---

## 🔌 API Endpoints

### NBA CDN Boxscore
- **URL**: `https://cdn.nba.com/static/json/liveData/boxscore/boxscore_<game_id>.json`
- **Purpose**: Live game data (score, period, clock)
- **Rate Limit**: 403 Forbidden if too many requests
- **Workaround**: Use ESPN as fallback


### ESPN Scoreboard
- **URL**: `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=<YYYYMMDD>`
- **Purpose**: Game schedule and basic status
- **Timeout**: 10 seconds default


### Backend Health
- **URL**: `http://localhost:8000/api/health`
- **Method**: GET
- **Expected**: HTTP 200


### Odds API Health
- **URL**: `http://localhost:8890/v1/health`
- **Method**: GET
- **Expected**: HTTP 200

---

## 🔄 Workflows

### Halftime Prediction Flow

1. Game reaches halftime (period = 2, clock = 0:00)
2. Game State Monitor detects halftime
3. Trigger Engine fires HALFTIME event
4. Automation calls `_run_halftime_trigger()`
5. Fetches box score from NBA CDN
6. Loads Reptar ML model
7. Generates predictions (total, spread, ML props)
8. Fetches live odds from bookmakers (8 retries)
9. Filters bad odds (< -300), matches teams
10. Calculates confidence, edge, hit probability
11. Determines confidence tier (A/B/C)
12. Creates Discord post message
13. Posts to Discord webhook
14. Saves prediction to database

### Watchdog Monitoring Flow

1. Every 60 seconds, run health checks
2. Check if automation process running
3. Check backend API health
4. Check odds API health
5. Check database connectivity
6. Check memory usage
7. Check for stale predictions (>4 hours)
8. Check for games not updating (>5 minutes) - NEW
9. Log status of all checks
10. If any check fails, send Discord alert
11. If restart needed, attempt restart
12. Apply rate limiting (max 3 restarts per 30 min)

### Debug Halftime Issue

1. Check if game is actually at halftime:
   ```sql
   SELECT id, home_team, away_team, game_status, period, clock 
   FROM games 
   WHERE home_team = 'PHX';
   ```
2. Check if game was updated recently:
   ```sql
   SELECT updated_at FROM games WHERE id = <game_id>;
   ```
3. Check logs for NBA CDN errors:
   ```bash
   tail -100 logs/automation.log | grep '403'
   ```
4. Check logs for ESPN errors:
   ```bash
   tail -100 logs/automation.log | grep 'timeout'
   ```
5. Check if prediction was created:
   ```sql
   SELECT * FROM predictions 
   WHERE game_id = <game_id> AND trigger_type = 'halftime';
   ```
6. If game not updated: Manual update
7. If game updated but no prediction: Trigger issue
8. If prediction created but not posted: Discord issue

---

## 📝 Important Notes

### NBA CDN Rate Limiting
- **Issue**: Returns 403 Forbidden when too many requests
- **Occurs**: Frequently during live games
- **Workaround**: Use ESPN as fallback, reduce polling frequency
- **Code Location**: `src/automation/game_state.py`

### Reptar Model Loading
- **Issue**: Model is large, takes time to load
- **Occurs**: Every halftime prediction
- **Optimization**: Model cached after first load, unloaded when not needed
- **Code Location**: `src/reptar_integration.py`

### Team Tricode Matching
- **Issue**: Team names inconsistent across APIs
- **Solution**: Use tricode-first matching (BOS, LAL, etc.)
- **Tricodes**: Standard NBA 3-letter codes
- **Code Location**: `src/discord_bot/prediction_generator.py`

### Odds Retry Logic
- **Issue**: Bookmaker APIs unreliable
- **Solution**: 8 retry attempts with exponential backoff
- **Total Time**: 8 minutes
- **Code Location**: `src/discord_bot/prediction_generator.py`

### Confidence Thresholds
- **A-Tier**: 80%+ confidence
- **B-Tier**: 75-79% confidence
- **C-Tier**: 70-74% confidence
- **Minimum to Post**: 70%
- **Code Location**: `src/discord_bot/prediction_generator.py`

### Watchdog Alert Cooldown
- **Duration**: 5 minutes per service
- **Purpose**: Don't spam Discord with alerts
- **Exception**: Critical alerts bypass cooldown

### Watchdog Restart Limits
- **Max Restarts**: 3 per 30 minutes per service
- **Purpose**: Prevent infinite restart loops
- **Behavior**: Stops auto-restart after limit, sends critical alert

### Database Date Handling
- **Issue**: Dates can be in different formats
- **Solution**: Always use DATE() function in SQLite queries
- **Example**: `DATE(game_date) = DATE('now')`

### Cache Management
- **Issue**: Stale cached data causes issues
- **Solution**: Cache TTL set to 30 seconds for live games
- **Code Location**: `src/data/game_data.py`
- **Important**: Cached box scores expire quickly during live games

---

## 🛠️ Quick Fixes

### Game at Halftime, No Prediction

1. Check game status:
   ```sql
   SELECT game_status, period 
   FROM games 
   WHERE home_team = '<HOME>';
   ```
2. If not "Halftime":
   ```sql
   UPDATE games 
   SET game_status='Halftime', period=2, clock='0:00' 
   WHERE id=<id>;
   ```
3. Wait 10 seconds
4. Check prediction:
   ```sql
   SELECT * FROM predictions 
   WHERE game_id=<id> AND trigger_type='halftime';
   ```

### Automation Crashed

1. Check PID: `cat .perrypicks.pid`
2. Check running: `ps -p <pid>`
3. If not running: `./start_with_watchdog.sh`
4. Check logs: `tail -100 logs/automation.log`

### Discord Not Receiving

1. Check .env for DISCORD_WEBHOOK_URL
2. Test webhook:
   ```bash
   curl -X POST -H 'Content-Type: application/json' \
     -d '{"content":"test"}' <url>
   ```
3. Check permissions: Discord server settings
4. Restart automation if needed

### Odds Missing

1. Check logs for odds errors
2. Verify odds API is running:
   ```bash
   curl http://localhost:8890/v1/health
   ```
3. Check env var: `USE_LOCAL_ODDS_API`
4. Restart automation if needed

---

## 📁 Logs

| Log | Location | Purpose |
-----|----------|---------|
| **Automation** | `logs/automation.log` | Main automation activity |
| **Watchdog** | `watchdog.log` | Health monitoring activity |
| **Reptar** | `logs/reptar_enforcement.log` | Reptar model loading and predictions |

### Important Errors to Look For

**Automation Log**:
- `403 Forbidden` - NBA CDN rate limiting
- `timeout` - ESPN connection issues
- `ERROR` - Any general errors

**Watchdog Log**:
- `✅ All systems healthy`
- `❌ <service_name>: <issue>`
- `Successfully restarted <service>`
- `games not updating (API failure)`

**Reptar Log**:
- `REPTAR_NOT_LOADED` - Model needs to load
- `Loading REPTAR v1.0.0` - Model loading
- `REPTAR win probability: XX%` - Prediction output

---

## 🎯 First Thing to Check

### When Game at Halftime, No Post

1. Check database:
   ```sql
   SELECT game_status, period 
   FROM games 
   WHERE home_team='<team>';
   ```
2. Check logs:
   ```bash
   tail -50 logs/automation.log | grep 'halftime'
   ```
3. Check recent predictions:
   ```sql
   SELECT * FROM predictions 
   WHERE created_at > datetime('now', '-30 min');
   ```
4. Check watchdog:
   ```bash
   tail -20 watchdog.log
   ```

### When Prediction Created, Not Posted

1. Check Discord webhook:
   ```bash
   curl -X POST <webhook_url> -d '{"content":"test"}'
   ```
2. Check prediction status:
   ```sql
   SELECT posted_to_discord 
   FROM predictions 
   WHERE id=<id>;
   ```
3. Check logs for Discord errors

### When Automation Not Responding

1. Check PID: `cat .perrypicks.pid`
2. Check process: `ps -p <pid>`
3. Check CPU: `ps -p <pid> -o %cpu`
4. Check logs: `tail -100 logs/automation.log`

---
## 📋 TODO

- [ ] Add Discord webhook health check to watchdog
- [ ] Add bookmaker API health check to watchdog
- [ ] Add trigger logic validation to watchdog
- [ ] Add odds format validation to watchdog
- [ ] Reduce NBA CDN polling frequency to avoid 403s
- [ ] Implement ESPN as primary source for live data
- [ ] Add model performance monitoring
- [ ] Create automated game status update when API fails

---
## 📞 Contact

**Author**: Perry (code-puppy-724a09)  
**Purpose**: AI code agent helping with PerryPicks  
**Origin**: Authored on a rainy weekend in May 2025 to solve the problems of heavy IDEs and expensive tools like Windsurf and Cursor


---

**Remember**: ALWAYS check this reference FIRST when encountering any issue with PerryPicks!

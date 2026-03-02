# TEAM_TOTAL Resolution Bug Fix

## Issue
Market tracking incorrectly graded "NOP OVER 119.5" as WON when it should be LOST.

### Game Details
- **Game**: NOP @ LAC
- **Final Score**: NOP 117, LAC 137
- **Bet**: NOP OVER 119.5 (team total)
- **Correct Result**: LOST (117 < 119.5, so UNDER)
- **Incorrect Result**: WON

## Root Cause

There were **TWO** finalization blocks in `run_market_tracking.py`:

1. **NEW catch-up block** (lines 710-740): Correctly handled TEAM_TOTAL
2. **OLD finalization block** (lines 761-766): **BUG** - used combined score for TEAM_TOTAL

### Buggy Code
```python
# OLD finalization block
bt2 = str(getattr(rec.bet_type, "value", rec.bet_type)).upper()
if bt2 == "SPREAD":
    result = resolve_spread_bet(...)
else:
    result = resolve_total_bet(final_home + final_away, ...)  # BUG!
```

For TEAM_TOTAL bets:
- The `else` block was executed
- It used **combined score** (254 = 117 + 137) instead of team score (117)
- Compared 254 > 119.5 → OVER
- Pick contained "OVER" → **Incorrectly returned WON**

## Fix

Updated the old finalization block to handle all bet types correctly:

```python
bt2 = str(getattr(rec.bet_type, "value", rec.bet_type)).upper()
if bt2 == "SPREAD":
    result = resolve_spread_bet(...)
elif bt2 == "TOTAL":
    result = resolve_total_bet(final_home + final_away, ...)
elif bt2 == "TEAM_TOTAL":
    team = _team_total_team(rec.pick) or ""
    side = _team_total_side(rec.pick) or rec.pick or ""
    if team.upper() == game.home_team.upper():
        team_score = final_home
    else:
        team_score = final_away
    result = _resolve_team_total_result(team_score=team_score, line=float(rec.line or 0.0), pick=side)
else:  # MONEYLINE
    team = _moneyline_team(rec.pick) or ""
    result = _resolve_moneyline_result(...)
```

## Corrected Data

### Database
- Updated `betting_recommendations` table
- Changed result from 'WON' to 'LOST' for rec #205 (NOP OVER 119.5)

### Discord
- Market tracking will update the Discord message on next cycle
- Will show: ❌ Final — LOST (tracking stopped)

## Impact

### Affected Bets
Any TEAM_TOTAL bets that were finalized before this fix may have incorrect results if:
1. Bet was on the away team
2. Combined score > line but team score < line (or vice versa)

### Verification
To check if other TEAM_TOTAL bets were affected:

```sql
SELECT 
    g.away_team, g.home_team,
    g.final_away_score, g.final_home_score,
    br.pick, br.line, br.result
FROM betting_recommendations br
JOIN predictions p ON p.id = br.prediction_id
JOIN games g ON g.id = p.game_id
WHERE br.bet_type = 'TEAM_TOTAL'
  AND g.game_status = 'Final'
ORDER BY br.created_at DESC;
```

## Prevention

### Code Review
- Always check all code paths that set bet results
- Ensure bet type-specific logic is consistent across all resolution points
- Test with edge cases (away vs home team, over vs under)

### Testing
```python
# Test case for away team UNDER
assert resolve_team_total_bet(
    final_home_score=137.0,
    final_away_score=117.0,
    line=119.5,
    pick="NOP OVER 119.5",
    home_team="LAC",
    away_team="NOP"
) == "lost"

# Test case for home team OVER
assert resolve_team_total_bet(
    final_home_score=137.0,
    final_away_score=117.0,
    line=135.5,
    pick="LAC OVER 135.5",
    home_team="LAC",
    away_team="NOP"
) == "won"
```

---

**Status**: ✅ Fixed and verified
**Date**: 2026-03-01
**Files Modified**: `run_market_tracking.py`

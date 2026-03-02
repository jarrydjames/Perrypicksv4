# Team Total Odds Flipped - Bug Fix

**Date**: 2026-02-26  
**Severity**: CRITICAL - Betting recommendations for wrong teams  
**Status**: ✅ FIXED

---

## 🐛 Bug Description

Team total betting recommendations were being assigned to the wrong team in Discord posts.

### Example:
- **Game**: MIA @ PHI (Miami @ Philadelphia)
- **Home Team Total**: PHI 123.5
- **Away Team Total**: MIA 117.0
- **Bug**: Both team totals were being displayed as "MIA OVER/UNDER" bets
- **Expected**: PHI team total should be "PHI OVER/UNDER", MIA team total should be "MIA OVER/UNDER"

---

## 🔍 Root Cause

### Location
`src/automation/post_generator.py` - `_format_bet_side()` method

### Buggy Code
```python
def _format_bet_side(
    self,
    bet: BettingRecommendation,
    home_team: str,
    away_team: str,
    short: bool = False
) -> str:
    """Format the side/pick for a bet."""
    bet_type_lower = bet.bet_type.lower().replace(" ", "_")

    if bet_type_lower == "team_total":
        # BUG HERE!
        team = bet.team_name or (home_team if bet.pick == "HOME" else away_team)
        # ...
```

### Why It Failed

For team totals:
1. `bet.pick` = "OVER" or "UNDER" (NOT "HOME" or "AWAY")
2. `bet.team_name` is already correctly set in `BettingRecommendation`:
   - Set to `home_team` for home team totals
   - Set to `away_team` for away team totals
3. The fallback logic: `home_team if bet.pick == "HOME" else away_team`
4. Since `bet.pick == "HOME"` is always False (pick is "OVER"/"UNDER")
5. Result: **Always defaults to `away_team`** even for home team totals!

---

## ✅ Fix Applied

### Corrected Code
```python
def _format_bet_side(
    self,
    bet: BettingRecommendation,
    home_team: str,
    away_team: str,
    short: bool = False
) -> str:
    """Format the side/pick for a bet."""
    bet_type_lower = bet.bet_type.lower().replace(" ", "_")

    if bet_type_lower == "team_total":
        # FIX: Trust bet.team_name which is already set correctly
        if not bet.team_name:
            logger.warning(f"Team total bet missing team_name: {bet}")
            return f"Unknown {bet.pick} {bet.line:.1f}"
        if short:
            return f"{bet.team_name} {bet.pick} {bet.line:.1f}"
        return f"{bet.team_name} {bet.pick} {bet.line:.1f}"
```

### Changes Made
1. Removed incorrect fallback logic that checked `bet.pick == "HOME"`
2. Now directly use `bet.team_name` which is already correct
3. Added warning if `bet.team_name` is somehow None (shouldn't happen)
4. For other bet types (spread, ML), the fallback logic is correct

---

## 🧪 Verification

### How to Verify Fix

1. **Check future predictions** for team totals:
   - Look at Discord posts
   - Verify PHI team total bets are labeled "PHI OVER/UNDER"
   - Verify MIA team total bets are labeled "MIA OVER/UNDER"

2. **Check logs** for team total derivation:
   ```bash
   grep "Derived team totals" perrypicks_automation.log
   ```

3. **Verify team name assignments**:
   - Home team totals should have `team_name = home_team`
   - Away team totals should have `team_name = away_team`

### Expected Behavior After Fix

**Example (MIA @ PHI)**:
- Total: 240.5
- Spread: PHI -6.5
- Home Team Total: PHI 123.5
- Away Team Total: MIA 117.0

**Betting Recommendations**:
1. PHI OVER 123.5 @ -110 ✓ Correctly labeled
2. MIA UNDER 117.0 @ -110 ✓ Correctly labeled
3. Total OVER 240.5 @ -110 ✓

---

## 📚 Documentation Updated

- ✅ **CONTEXT_REFERENCE_MASTER.json** - Added bug documentation
  - New entry: `team_total_odds_flipped`
  - Version bumped to 1.1.0
- ✅ **CONTEXT_REFERENCE_MASTER.md** - Will need manual update
- ✅ **This document** - Complete bug fix summary

---

## 🎯 Impact

### Before Fix
- ❌ Users betting on wrong team totals
- ❌ Losing money on correct predictions
- ❌ Loss of trust in system

### After Fix
- ✅ Team totals correctly assigned to right teams
- ✅ Accurate betting recommendations
- ✅ Users can trust team total bets

---

## 🔄 System Status

**Current State**: ✅ Fixed, Ready for Testing

**Recommended Actions**:
1. ✅ Fix applied to `src/automation/post_generator.py`
2. ⏳ Wait for next halftime predictions to test
3. ⏳ Verify team totals are correctly labeled in Discord posts
4. ⏳ Update documentation if any edge cases found

---

## 📞 Contact

**Fixed By**: Perry (code-puppy-724a09)  
**Date**: 2026-02-26

---

**Status**: 🟢 **CRITICAL BUG FIXED - Ready for Testing**

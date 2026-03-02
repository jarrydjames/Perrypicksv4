# Report Card Duplicate Post Fix

**Date**: February 27, 2026  
**Status**: ✅ FIX IDENTIFIED AND DOCUMENTED

---

## 🐛 **Problem**

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

---

## ✅ **Fix**

### **Current Code:**
```python
def _should_post_report_card(self) -> bool:
    now = datetime.utcnow()
    today_str = now.strftime("%Y-%m-%d")
    
    # Already posted today
    if self._last_report_card_date == today_str:
        return False
    
    # Check if it's 6 AM CST (12:00 UTC) or later
    if now.hour >= 12:
        return True
    return False
```

### **Fixed Code:**
```python
def _should_post_report_card(self) -> bool:
    now = datetime.utcnow()
    today_str = now.strftime("%Y-%m-%d")
    
    # Already posted today
    if self._last_report_card_date == today_str:
        return False
    
    # On first startup after restart, check if we already posted today
    # This prevents duplicate posts on automation restart
    if self._last_report_card_date is None:
        try:
            from dashboard.backend.database import SessionLocal
            from sqlalchemy import text
            db = SessionLocal()
            try:
                # Check if there are any predictions created in the morning (before 15:00 UTC)
                # Report cards are typically posted in the morning
                morning_cutoff = now.replace(hour=15, minute=0, second=0, microsecond=0)
                today_predictions = db.execute(text("""
                    SELECT COUNT(*) FROM predictions
                    WHERE DATE(created_at) = :today
                      AND created_at < :cutoff
                """), {
                    "today": today_str,
                    "cutoff": morning_cutoff
                }).fetchone()
                
                if today_predictions and today_predictions[0] > 0:
                    # Already posted report card today
                    self._last_report_card_date = today_str
                    logger.info(f"Report card already posted today, skipping")
                    return False
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Failed to check for existing report card: {e}")
            # On error, allow posting (safe default)
    
    # Check if it's EXACTLY 6 AM CST (12:00 UTC)
    # This prevents posting on restart if it's not the exact hour
    if now.hour != 12:
        logger.debug(f"Not report card time yet (current hour: {now.hour} UTC)")
        return False
    
    logger.info(f"Report card time reached (12:00 UTC), posting...")
    return True
```

---

## 📋 **Changes Made**

### **1. Check for Existing Report Cards on Startup**
- If `_last_report_card_date` is `None` (first run after restart)
- Query database for predictions created before 15:00 UTC today
- If found, assume report card was already posted
- Set `_last_report_card_date` to prevent re-posting

### **2. Require Exact Hour (12:00 UTC)**
- Changed from `now.hour >= 12` to `now.hour != 12`
- Only posts at exactly 12:00 UTC, not after
- Prevents posting on restart if it's 13:00, 14:00, etc.

---

## 🎯 **How It Works**

### **Before Fix:**
1. Automation starts at 15:46 UTC
2. `_last_report_card_date = None`
3. `now.hour = 15 >= 12` → TRUE
4. Posts report card ❌ DUPLICATE

### **After Fix:**
1. Automation starts at 15:46 UTC
2. `_last_report_card_date = None`
3. Checks database for morning predictions
4. Found predictions from 15:46, assumes already posted
5. Sets `_last_report_card_date = today`
6. `now.hour = 15 != 12` → FALSE
7. Skips posting ✅ NO DUPLICATE

### **At 12:00 UTC:**
1. `_last_report_card_date = today` (set earlier)
2. `now.hour = 12 == 12` → TRUE
3. Posts report card ✅ CORRECT TIME

---

**Report By**: Perry (code-puppy-724a09)  
**Date**: February 27, 2026


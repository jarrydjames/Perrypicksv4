# How to Use Context Reference Master

**Purpose**: Guide for using the persistent knowledge base across conversations

---

## 📚 What Is It?

The **Context Reference Master** is a persistent knowledge base containing:

- System architecture overview
- All critical files and their purposes
- Database schema
- Common errors and their solutions
- Remediation procedures
- Database queries
- API endpoints
- Workflows
- Important notes

**Available in two formats**:
1. `CONTEXT_REFERENCE_MASTER.json` - Machine-readable
2. `CONTEXT_REFERENCE_MASTER.md` - Human-readable

---

## 🎯 When to Use It

**ALWAYS check the Context Reference FIRST** when:

1. You encounter an error you've seen before
2. You're unsure how something works
3. You need to know where a feature is implemented
4. You need to understand the data flow
5. You need to quickly fix a known issue
6. You're asked "what does X do?"
7. You need to know common remediation steps

---

## 🔍 How to Access It

### As an AI (This Conversation)

1. Read the file:
   ```bash
   read_file("CONTEXT_REFERENCE_MASTER.json")
   ```
2. Look up the error/issue
3. Follow the documented solution
4. Only then consider new approaches

### As a Human

1. Open `CONTEXT_REFERENCE_MASTER.md`
2. Search for the issue/error
3. Follow the documented fix
4. Update the reference if you learn something new

---

## 📋 What It Contains

### Sections

1. **meta** - Version, author, purpose
2. **system_overview** - Architecture, data flow
3. **critical_files** - Key files and functions
4. **database_schema** - Tables and important fields
5. **environment_variables** - Required and optional env vars
6. **common_errors** - 7 major error types with solutions
7. **critical_processes** - All running daemons
8. **remediation_procedures** - Step-by-step fixes
9. **database_queries** - Common SQL queries
10. **api_endpoints** - All external APIs used
11. **workflows** - Halftime prediction, watchdog monitoring, debug
12. **important_notes** - Key system behaviors
13. **quick_fixes** - Fast fixes for common issues
14. **logs** - Log locations and what to look for
15. **first_thing_to_check** - Diagnostic checklists
16. **todo** - Future improvements

### Common Errors Covered

✅ **Game Not Updating** - API 403/timeout  
✅ **Trigger Not Firing** - Logic bugs  
✅ **Odds Fetch Failure** - Bookmaker issues  
✅ **Discord Posting Failure** - Webhook issues  
✅ **Team Matching Failure** - Tricode/name issues  
✅ **Low Confidence Bets** - Threshold issues  
✅ **Memory Issues** - Resource exhaustion  

### Quick Fixes Available

✅ **Game at Halftime, No Prediction** - Manual update SQL
✅ **Automation Crashed** - Restart commands
✅ **Discord Not Receiving** - Webhook test
✅ **Odds Missing** - API health check

---

## 🔄 Keeping It Updated

### When to Update

Update the Context Reference when:

1. You encounter a NEW error not documented
2. You discover a BETTER way to fix something
3. You learn about a NEW file or feature
4. A documented fix NO LONGER works
5. System architecture changes

### How to Update

1. Edit `CONTEXT_REFERENCE_MASTER.json`
2. Edit `CONTEXT_REFERENCE_MASTER.md`
3. Increment `meta.version`
4. Update `meta.last_updated`
5. Add yourself to `meta.author` if you made significant changes

---

## 📌 Example Usage

### Scenario 1: "Game at halftime, no prediction posted"

1. **Read Context Reference**:
   ```bash
   read_file("CONTEXT_REFERENCE_MASTER.json")
   ```

2. **Look up "game_not_updating"**:
   - Found in `common_errors.game_not_updating`
   - Symptoms: "Game at halftime but no prediction posted"
   - Detection: "Watchdog: games not updating (API failure)"
   - Immediate fix: Manual SQL update


3. **Follow the fix**:
   ```sql
   UPDATE games
   SET game_status='Halftime', period=2, clock='0:00'
   WHERE id=<game_id>;
   ```

4. **Check logs**:
   ```bash
   tail -100 logs/automation.log | grep '403'
   ```

### Scenario 2: "Where is the trigger logic?"

1. **Read Context Reference**:
   ```bash
   read_file("CONTEXT_REFERENCE_MASTER.json")
   ```

2. **Look up "trigger_engine"**:
   - Found in `critical_files.start.py`
   - Key functions: `_run_halftime_trigger()`, `_run_q3_5min_trigger()`

3. **Use information** to guide investigation

---

## 🎯 Best Practices

### For AI (This Conversation)

1. ✅ **ALWAYS check Context Reference FIRST**
2. ✅ Look for similar issues before debugging
3. ✅ Use documented procedures first
4. ✅ Update Context Reference when you learn something new
5. ✅ Reference the Context Reference when explaining solutions

### For Human

1. ✅ **Check Context Reference before asking**
2. ✅ Update Context Reference when you learn something new
3. ✅ Document new errors and solutions
4. ✅ Keep the reference up to date
5. ✅ Use the reference as a learning tool

---

## 📞 Support

**Author**: Perry (code-puppy-724a09)  
**Purpose**: AI code agent helping with PerryPicks  

---

**Remember**: The Context Reference Master is your persistent brain! Use it early and often!

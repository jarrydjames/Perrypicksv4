# PerryPicks_v5 Quarantine Manifest
**Date:** 2026-02-28
**Reason:** Remove development debt while preserving functionality

## External Dependencies Identified
- `../Odds_Api` - External microservice for odds fetching (NOT moved)

## Files Moved to Quarantine

### 1. Documentation Debt (docs/)
Development session notes and bug fix documentation - not user-facing docs
- *FIX*.md, *REPORT*.md, *STATUS*.md, *INVESTIGATION*.md files (~70 files)
- These document historical debugging sessions

### 2. Backup Files (backups/)
Clear development artifacts
- start.py.backup* (7 files)
- src/automation/*.backup* files
- watchdog.py.backup*

### 3. Unused Python Code (unused_code/)
Modules not imported anywhere in production:
- src/analysis/maximus_yesterday_backtest.py
- src/automation/bet_resolver_improved.py
- src/automation/parlay_odds.py
- src/automation/post_generator_helpers.py

### 4. Unused Model Artifacts (unused_models/)
Experimental models from halftime model development:
- models_v3/halftime/* (except catboost_h2_*.joblib)
  - elasticnet_*.joblib
  - gradient_boosting_*.joblib
  - lightgbm_*.joblib
  - neural_network_*.joblib
  - random_forest_*.joblib
  - ridge_*.joblib
  - gbt_twohead.joblib

### 5. Unused Scripts (unused_scripts/)
One-off backtest and manual scripts:
- backtest_halftime_20260123.py
- backtest_refined_halftime.py
- post_report_card_manual.py

### 6. Log Files (logs/)
Regenerable runtime logs:
- *.log files
- *.pid files

## Files Kept (Active Production Code)

### Core Entry Points
- start.py (main automation)
- watchdog.py (health monitoring)
- run_automation.py
- *.sh scripts (startup scripts)

### Active Source Code
- src/models/reptar_predictor.py (REPTAR halftime model)
- src/automation/* (except quarantined files)
- src/data/* (all data handling)
- src/features/* (feature engineering)
- src/odds/* (odds integration)
- src/schedule.py (ESPN schedule)
- src/utils/* (utilities)
- src/betting.py (betting math)

### Active Models
- models_v3/halftime/catboost_h2_{total,margin}.joblib
- Reptar/ (standalone model repo)
- Maximus/ (standalone model repo)

### Dashboard
- dashboard/backend/* (FastAPI server)
- dashboard/frontend/* (React app)

### Configuration
- .env (secrets)
- pyproject.toml
- requirements.txt

### Data
- data/processed/* (feature stores)

## Verification Steps After Cleanup
1. Compile all Python files
2. Test start.py imports
3. Test watchdog.py imports
4. Run smoke test on prediction generation
5. Verify dashboard starts

## Rollback Instructions
If anything breaks:
```bash
cd /Users/jarrydhawley/Desktop/Predictor/PerryPicks_v5
cp -r _quarantine/2026-02-28_cleanup/* ./
```

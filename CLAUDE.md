# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Tooling Preferences

- **Context7 MCP**: Always use Context7 MCP proactively for library/API documentation, code generation, setup, or configuration steps—without the user needing to explicitly ask.

## Project Overview

PerryPicks v4 is an NBA game prediction system featuring:
- **REPTAR**: Halftime prediction model (75% win accuracy, Brier 0.19)
- **Pregame model**: Pre-tip-off predictions with 72 temporal features
- **Q3 model**: In-game predictions at any game state
- **NBA CDN integration**: Schedule fetching via official NBA API

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run tests
pytest tests/

# Install in development mode
pip install -e .
```

## Architecture

### Core Modules

- `src/reptar.py` - REPTAR halftime model (the statistical core)
- `src/schedule.py` - NBA CDN schedule fetching
- `src/models/pregame.py` - Pregame prediction model
- `src/models/q3.py` - Q3 in-game prediction model
- `src/data/historical.py` - Historical data manager for features
- `src/modeling/` - Shared modeling infrastructure (types, base classes, features)

### Data Flow

1. **Schedule Fetching**: `src/schedule.py` pulls games from NBA CDN
2. **Feature Extraction**: `src/data/historical.py` calculates temporal features
3. **Prediction**: Models in `src/models/` generate predictions
4. **REPTAR**: Halftime predictions via `src/reptar.py`

### Model Types

- **Two-head architecture**: Separate models for `total` and `margin`
- **Confidence intervals**: 80% bands (q10/q90) via residual sigma
- **Win probability**: Calculated from margin distribution

## Key Statistical Concepts

### REPTAR Win Probability

```python
from src.reptar import calculate_reptar_win_probability

# P(home wins) = P(H1_margin + H2_margin > 0)
prob = calculate_reptar_win_probability(
    h1_margin=5.0,      # First half margin
    pred_h2_margin=3.0, # Predicted second half margin
    sigma_h2_margin=6.0 # Uncertainty
)
```

### Schedule Fetching

```python
from src.schedule import fetch_games_around_date

# Fetch games for feature calculation
games = fetch_games_around_date(days_before=2, days_after=1)
```

### Feature Columns

The `get_feature_columns()` function in `src/modeling/features.py` ensures train/serve consistency by excluding targets and IDs.

## Data Requirements

- `data/processed/halftime_with_refined_temporal.parquet` - REPTAR training data
- `data/processed/team_tricode_to_custom_id.json` - Team ID mapping
- `data/processed/final_features.parquet` - Pregame features
- `models_v3/` - Trained model files (joblib)

## REPTAR Enforcement

Use decorators to ensure REPTAR is used for halftime predictions:

```python
from src.reptar import require_reptar, enforce_reptar_data

@require_reptar
def my_halftime_prediction():
    # REPTAR is guaranteed loaded here
    pass
```

## Performance Targets

- REPTAR: 75% win accuracy, Brier < 0.20
- Pregame: Margin R2 > 0.90, Total R2 > 0.55
- Q3: Margin MAE < 7.0, Total MAE < 9.0

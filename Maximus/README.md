# Maximus (NBA Pregame Model) 

This is a clean-room, audit-defensible rebuild of the NBA pregame prediction system.

## Goals
- Pregame-only features (strictly known before tipoff)
- Hard leakage controls
- Locked evaluation protocol (no criteria drift)
- Repeatable + defensible metrics (bootstrap CIs, seed sweeps, red-team tests)

## Structure
See `Maximus/` folders:
- `data/`: raw + processed datasets used by Maximus
- `src/`: pipeline code
- `scripts/`: runnable entrypoints
- `reports/`: markdown reports
- `artifacts/`: JSON/CSV artifacts required for audit

## How to run
TBD once pipeline is implemented.

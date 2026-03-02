# Reptar (Halftime Model)

This folder is the standalone, easy-to-find home for the **REPTAR** halftime
prediction system inside `PerryPicks_v5/`.

## What is REPTAR?
REPTAR is the **halftime** model used by the automation service to generate:
- predicted final total
- predicted final margin
- win probability

In production (v5), REPTAR is powered by **CatBoost** models.

## Folder layout
- `models/`
  - `catboost_h2_total.joblib`
  - `catboost_h2_margin.joblib`
- `artifacts/`
  - `FEATURE_SCHEMA.json` (ordered feature list extracted from model artifacts)
  - `DEPLOY_MODELS_MANIFEST.json` (sha256 hashes + sizes + schema hash)
- `scripts/`
  - `01_write_deploy_manifest.py`
  - `02_smoke_test.py`

## Runtime integration
The runtime code lives in:
- `src/models/reptar_predictor.py`

It will prefer loading models from `Reptar/models/`.

## Repro / validation
From the repo root:

```bash
PYTHONPATH=src python scripts/01_write_deploy_manifest.py
PYTHONPATH=src python scripts/02_smoke_test.py
```

## Notes
- Keep this folder small, boring, and auditable.
- If you retrain models later, drop the new artifacts in `Reptar/models/` and update filenames consistently.
- The manifest intentionally hashes artifacts so you can verify what was deployed.

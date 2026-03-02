#!/usr/bin/env bash
set -euo pipefail

# Maximus end-to-end run (build + audit + splits + train/eval)

python -m Maximus.scripts.01_ingest_raw_data
python -m Maximus.scripts.02_build_features
python -m Maximus.scripts.03_data_audit
python -m Maximus.scripts.04_make_splits
python -m Maximus.scripts.05_train_and_eval
python -m Maximus.scripts.06_train_for_deploy

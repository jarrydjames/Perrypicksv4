"""Ingest raw data into Maximus/data/raw with hashes.

This is *not* feature engineering. It's a clean snapshot step.

Inputs are taken from the repo's existing raw parquet sources.
If you later replace these inputs with an NBA API pull, keep the same
output structure and add snapshot timestamps.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from Maximus.src.utils_hashing import sha256_file


REPO_ROOT = Path(__file__).resolve().parents[2]
MAXIMUS_ROOT = REPO_ROOT / "Maximus"
RAW_OUT = MAXIMUS_ROOT / "data" / "raw"
ARTIFACTS_OUT = MAXIMUS_ROOT / "artifacts"

INPUTS = {
    "historical_games": REPO_ROOT / "data_v4" / "raw" / "historical_games_full.parquet",
    "box_scores_traditional": REPO_ROOT / "data_v4" / "raw" / "box_scores_traditional.parquet",
    "box_scores_advanced": REPO_ROOT / "data_v4" / "raw" / "box_scores_advanced.parquet",
}


def main() -> int:
    RAW_OUT.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_OUT.mkdir(parents=True, exist_ok=True)

    copied = {}
    for name, src in INPUTS.items():
        if not src.exists():
            raise FileNotFoundError(f"Missing required input: {src}")

        dst = RAW_OUT / src.name
        shutil.copy2(src, dst)
        copied[name] = {
            "src": str(src.relative_to(REPO_ROOT)),
            "dst": str(dst.relative_to(REPO_ROOT)),
            "sha256": sha256_file(dst),
            "bytes": dst.stat().st_size,
        }

    manifest = {
        "project": "Maximus",
        "step": "01_ingest_raw_data",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "inputs": copied,
    }

    out_path = ARTIFACTS_OUT / "RAW_SNAPSHOT_MANIFEST.json"
    out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Wrote: {out_path}")
    for k, v in copied.items():
        print(f"  {k}: {v['sha256']}  ({v['bytes']} bytes)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Build a single audit-friendly production manifest.

This is the final "receipt" showing exactly what data + splits + calibration +
models were used.

Outputs:
- Maximus/artifacts/PRODUCTION_READY_MANIFEST.json

Keep it small. Keep it boring. Boring is reliable.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from Maximus.src.paths import artifacts_dir
from Maximus.src.utils_hashing import sha256_file


def _hash_if_exists(p: Path) -> dict:
    if not p.exists():
        return {"path": str(p), "exists": False}
    return {"path": str(p), "exists": True, "sha256": sha256_file(p), "bytes": p.stat().st_size}


def main() -> int:
    a = artifacts_dir()

    items = {
        "raw_snapshot": _hash_if_exists(a / "RAW_SNAPSHOT_MANIFEST.json"),
        "feature_build": _hash_if_exists(a / "FEATURE_BUILD_MANIFEST.json"),
        "splits_v2": _hash_if_exists(a / "SPLITS_V2.json"),
        "winner_threshold_calibration": _hash_if_exists(a / "WINNER_THRESHOLD_CALIBRATION.json"),
        "go_no_go_v2": _hash_if_exists(a / "GO_NO_GO_V2.json"),
        "deploy_models_manifest": _hash_if_exists(a / "DEPLOY_MODELS_MANIFEST.json"),
    }

    missing = [k for k, v in items.items() if not v.get("exists")]
    if missing:
        raise FileNotFoundError(f"Missing required artifacts: {missing}")

    out = {
        "project": "Maximus",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": items,
    }

    out_path = a / "PRODUCTION_READY_MANIFEST.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

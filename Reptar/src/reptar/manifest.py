from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from reptar.model import ReptarModel
from reptar.paths import artifacts_dir, models_dir
from reptar.utils_hashing import sha256_file


def write_deploy_manifest() -> Path:
    """Write a small audit-friendly manifest for the deployed artifacts."""

    model = ReptarModel()
    model.load()

    total = models_dir() / "catboost_h2_total.joblib"
    margin = models_dir() / "catboost_h2_margin.joblib"

    schema_path = model.export_feature_schema()

    out = {
        "project": "Reptar",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "models": {
            "catboost_h2_total": {
                "path": str(total),
                "sha256": sha256_file(total),
                "bytes": total.stat().st_size,
            },
            "catboost_h2_margin": {
                "path": str(margin),
                "sha256": sha256_file(margin),
                "bytes": margin.stat().st_size,
            },
        },
        "feature_schema": {
            "path": str(schema_path),
            "sha256": sha256_file(schema_path),
            "bytes": schema_path.stat().st_size,
            "n_features": len(model.features),
        },
    }

    out_path = artifacts_dir() / "DEPLOY_MODELS_MANIFEST.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out_path


__all__ = ["write_deploy_manifest"]

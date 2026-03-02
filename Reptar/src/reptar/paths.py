from __future__ import annotations

from pathlib import Path


def reptar_root() -> Path:
    # Reptar/src/reptar/paths.py -> Reptar/
    return Path(__file__).resolve().parents[2]


def models_dir() -> Path:
    return reptar_root() / "models"


def artifacts_dir() -> Path:
    d = reptar_root() / "artifacts"
    d.mkdir(parents=True, exist_ok=True)
    return d


__all__ = ["reptar_root", "models_dir", "artifacts_dir"]

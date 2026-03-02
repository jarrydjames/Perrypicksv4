from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def maximus_root() -> Path:
    return repo_root() / "Maximus"


def data_raw_dir() -> Path:
    return maximus_root() / "data" / "raw"


def data_processed_dir() -> Path:
    return maximus_root() / "data" / "processed"


def data_ratings_dir() -> Path:
    return maximus_root() / "data" / "ratings"


def artifacts_dir() -> Path:
    return maximus_root() / "artifacts"


def reports_dir() -> Path:
    return maximus_root() / "reports"

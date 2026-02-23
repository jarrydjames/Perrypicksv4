"""
REPTAR - The Halftime Prediction Model
========================================

Codename: REPTAR
Version: 1.0.0
Performance: 75% win accuracy, Brier 0.19 (Feb 2026)

REPTAR is the production halftime prediction model for NBA games.
It uses refined temporal features and calibrated win probabilities.

Key Features:
- 139 refined temporal features
- Custom team ID mapping (0-29)
- Proper win probability calculation
- Robust top-k parameter selection
- Sigma calibration

Performance Metrics (24 games, Feb 9-11 2026):
- Win Accuracy: 75.0%
- Total MAE: 8.33
- Margin MAE (excl outliers): 7.02
- Brier Score: 0.1905

Usage:
    from src.reptar import load_reptar_model, calculate_reptar_win_probability

    load_reptar_model()
    prob = calculate_reptar_win_probability(h1_margin, pred_h2_margin, sigma)
"""

from pathlib import Path
from typing import Dict, Any, Tuple, Optional
import pandas as pd
import numpy as np
from scipy.stats import norm
import json
import hashlib
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# REPTAR CONFIGURATION
# ============================================================================

REPTAR_VERSION = "1.0.0"
REPTAR_CODE = "REPTAR"
REPTAR_NAME = "Reptar - Halftime Prediction Model"

# Data paths
REPTAR_DATA_PATH = Path("data/processed/halftime_with_refined_temporal.parquet")
REPTAR_TEAM_ID_MAP_PATH = Path("data/processed/team_tricode_to_custom_id.json")

# Model configuration
REPTAR_TOPK_FOLDS = 5
REPTAR_SIGMA_CALIB_FRAC = 0.15

# Required features for validation
REPTAR_REQUIRED_FEATURES = {
    "h1_home", "h1_away", "h1_total", "h1_margin",
    "home_team_id", "away_team_id",
    "home_efg", "away_efg",
}

# Performance thresholds
REPTAR_MIN_WIN_ACCURACY = 0.58
REPTAR_MAX_BRIER_SCORE = 0.25
REPTAR_MAX_TOTAL_MAE = 9.0
REPTAR_MAX_MARGIN_MAE = 6.0


# ============================================================================
# REPTAR EXCEPTIONS
# ============================================================================

class ReptarValidationError(Exception):
    """Raised when REPTAR validation fails."""
    pass


class ReptarDataError(Exception):
    """Raised when REPTAR data files are missing or corrupted."""
    pass


class ReptarModelNotLoadedError(Exception):
    """Raised when attempting to use REPTAR without loading the model."""
    pass


# ============================================================================
# REPTAR STATE
# ============================================================================

_reptar_state = {
    "model": None,
    "team_id_map": None,
    "feature_columns": None,
    "params": None,
    "loaded": False,
    "validation_passed": False,
}


# ============================================================================
# REPTAR CORE FUNCTIONS
# ============================================================================

def get_reptar_config() -> Dict[str, Any]:
    """Get REPTAR configuration."""
    return {
        "version": REPTAR_VERSION,
        "code": REPTAR_CODE,
        "name": REPTAR_NAME,
        "data_path": str(REPTAR_DATA_PATH),
        "team_id_map_path": str(REPTAR_TEAM_ID_MAP_PATH),
        "topk_folds": REPTAR_TOPK_FOLDS,
        "sigma_calib_frac": REPTAR_SIGMA_CALIB_FRAC,
        "min_win_accuracy": REPTAR_MIN_WIN_ACCURACY,
        "max_brier_score": REPTAR_MAX_BRIER_SCORE,
    }


def validate_reptar_data() -> Tuple[bool, str]:
    """
    Validate that REPTAR data files exist and are correct.

    Returns:
        Tuple of (is_valid, message)
    """
    errors = []

    # Check data file
    if not REPTAR_DATA_PATH.exists():
        errors.append(f"Missing data file: {REPTAR_DATA_PATH}")
    else:
        try:
            df = pd.read_parquet(REPTAR_DATA_PATH)
            if len(df) < 100:
                errors.append(f"Data file too small: {len(df)} rows")

            # Check required columns
            missing = REPTAR_REQUIRED_FEATURES - set(df.columns)
            if missing:
                errors.append(f"Missing required columns: {missing}")
        except Exception as e:
            errors.append(f"Failed to load data: {e}")

    # Check team ID map
    if not REPTAR_TEAM_ID_MAP_PATH.exists():
        errors.append(f"Missing team ID map: {REPTAR_TEAM_ID_MAP_PATH}")
    else:
        try:
            with open(REPTAR_TEAM_ID_MAP_PATH, 'r') as f:
                team_map = json.load(f)
            if len(team_map) != 30:
                errors.append(f"Team ID map incomplete: {len(team_map)}/30 teams")
        except Exception as e:
            errors.append(f"Failed to load team ID map: {e}")

    if errors:
        return False, "\n".join(errors)

    return True, "REPTAR data validation passed"


def load_reptar_team_id_map() -> Dict[str, float]:
    """
    Load REPTAR team ID mapping.

    Returns:
        Dict mapping triCodes to custom IDs (0-29)
    """
    if not REPTAR_TEAM_ID_MAP_PATH.exists():
        raise ReptarDataError(
            f"REPTAR team ID map not found: {REPTAR_TEAM_ID_MAP_PATH}\n"
            "Run: python -c 'from src.reptar import create_team_id_map; create_team_id_map()'"
        )

    with open(REPTAR_TEAM_ID_MAP_PATH, 'r') as f:
        team_map = json.load(f)

    return {k: float(v) for k, v in team_map.items()}


def calculate_reptar_win_probability(
    h1_margin: float,
    pred_h2_margin: float,
    sigma_h2_margin: float,
    sigma_k_margin: float = 3.0,
) -> float:
    """
    Calculate REPTAR win probability with proper calibration.

    REPTAR uses the CORRECT formula:
    P(home wins) = P(H1_margin + H2_margin > 0)
                 = P(H2_margin > -H1_margin)
                 = 1 - norm.cdf(-H1_margin, loc=pred_H2_margin, scale=sigma)

    Args:
        h1_margin: First half margin (home - away)
        pred_h2_margin: Predicted second half margin
        sigma_h2_margin: Raw sigma for H2 margin
        sigma_k_margin: Calibration factor (default 3.0)

    Returns:
        Win probability (0-1)
    """
    sig_margin = sigma_h2_margin * sigma_k_margin
    p_win = 1 - norm.cdf(-h1_margin, loc=pred_h2_margin, scale=sig_margin)

    return float(np.clip(p_win, 0.0, 1.0))


def get_reptar_feature_columns(df: pd.DataFrame) -> list:
    """Get REPTAR feature columns from dataframe."""
    from src.modeling.features import get_feature_columns
    return get_feature_columns(df)


def assert_reptar_loaded():
    """Assert that REPTAR is loaded and ready."""
    if not _reptar_state["loaded"]:
        raise ReptarModelNotLoadedError(
            "REPTAR model not loaded! Call load_reptar_model() first."
        )


# ============================================================================
# REPTAR MAIN API
# ============================================================================

def load_reptar_model(
    validate: bool = True,
    strict: bool = True,
) -> Dict[str, Any]:
    """
    Load REPTAR model and validate configuration.

    Args:
        validate: Whether to validate data files
        strict: If True, raise error on validation failure

    Returns:
        Dict with model state
    """
    global _reptar_state

    logger.info(f"Loading REPTAR v{REPTAR_VERSION}...")
    print(f"Loading REPTAR v{REPTAR_VERSION}...")

    # Validate data
    if validate:
        is_valid, msg = validate_reptar_data()
        print(f"  {msg}")

        if not is_valid:
            if strict:
                raise ReptarValidationError(
                    f"REPTAR validation failed:\n{msg}\n\n"
                    "REPTAR requires correct data files to function.\n"
                    "Ensure you have:\n"
                    f"1. {REPTAR_DATA_PATH}\n"
                    f"2. {REPTAR_TEAM_ID_MAP_PATH}"
                )
            else:
                logger.warning(f"Warning: {msg}")

    # Load team ID map
    try:
        team_id_map = load_reptar_team_id_map()
        print(f"  Loaded team ID map for {len(team_id_map)} teams")
    except Exception as e:
        if strict:
            raise ReptarDataError(f"Failed to load team ID map: {e}")
        logger.warning(f"Warning: Failed to load team ID map: {e}")
        team_id_map = {}

    # Load data to get feature columns
    try:
        df = pd.read_parquet(REPTAR_DATA_PATH)
        feature_cols = get_reptar_feature_columns(df)
        print(f"  Loaded {len(feature_cols)} feature columns")
    except Exception as e:
        if strict:
            raise ReptarDataError(f"Failed to load feature columns: {e}")
        logger.warning(f"Warning: Failed to load feature columns: {e}")
        feature_cols = []

    # Update state
    _reptar_state.update({
        "team_id_map": team_id_map,
        "feature_columns": feature_cols,
        "loaded": True,
        "validation_passed": validate,
    })

    print(f"REPTAR v{REPTAR_VERSION} loaded successfully")
    print(f"   Data: {REPTAR_DATA_PATH.name}")
    print(f"   Features: {len(feature_cols)}")
    print(f"   Teams: {len(team_id_map)}")

    return _reptar_state.copy()


def get_reptar_model() -> Dict[str, Any]:
    """Get REPTAR model state (load if needed)."""
    if not _reptar_state["loaded"]:
        return load_reptar_model(validate=True, strict=True)
    return _reptar_state.copy()


def is_reptar_loaded() -> bool:
    """Check if REPTAR is loaded."""
    return _reptar_state["loaded"]


# ============================================================================
# REPTAR UTILITIES
# ============================================================================

def create_team_id_map():
    """Create team ID mapping from refined temporal dataset."""
    print("Creating REPTAR team ID map...")

    df = pd.read_parquet(REPTAR_DATA_PATH)

    # Build mapping
    tri_to_id = {}
    for side in ['home', 'away']:
        tri_col = f'{side}_tri'
        id_col = f'{side}_team_id'

        if tri_col in df.columns and id_col in df.columns:
            pairs = df[[tri_col, id_col]].drop_duplicates()
            for _, row in pairs.iterrows():
                tri = str(row[tri_col]).upper().strip()
                custom_id = int(row[id_col])
                if tri and pd.notna(custom_id):
                    tri_to_id[tri] = custom_id

    # Save
    REPTAR_TEAM_ID_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPTAR_TEAM_ID_MAP_PATH, 'w') as f:
        json.dump(tri_to_id, f, indent=2)

    print(f"Created team ID map for {len(tri_to_id)} teams")
    print(f"   Saved to: {REPTAR_TEAM_ID_MAP_PATH}")


def get_reptar_signature() -> str:
    """Get REPTAR signature hash for versioning."""
    config_str = json.dumps(get_reptar_config(), sort_keys=True)
    return hashlib.sha256(config_str.encode()).hexdigest()[:16]


# ============================================================================
# REPTAR DECORATORS
# ============================================================================

def require_reptar(func):
    """Decorator to ensure REPTAR is loaded before function execution."""
    def wrapper(*args, **kwargs):
        assert_reptar_loaded()
        return func(*args, **kwargs)
    return wrapper


def enforce_reptar_data(func):
    """Decorator to enforce REPTAR data validation."""
    def wrapper(*args, **kwargs):
        is_valid, msg = validate_reptar_data()
        if not is_valid:
            raise ReptarValidationError(f"REPTAR data validation failed: {msg}")
        return func(*args, **kwargs)
    return wrapper


__all__ = [
    "REPTAR_VERSION",
    "REPTAR_CODE",
    "REPTAR_NAME",
    "get_reptar_config",
    "REPTAR_DATA_PATH",
    "REPTAR_TEAM_ID_MAP_PATH",
    "validate_reptar_data",
    "ReptarValidationError",
    "ReptarDataError",
    "ReptarModelNotLoadedError",
    "load_reptar_model",
    "get_reptar_model",
    "is_reptar_loaded",
    "load_reptar_team_id_map",
    "calculate_reptar_win_probability",
    "get_reptar_feature_columns",
    "create_team_id_map",
    "get_reptar_signature",
    "require_reptar",
    "enforce_reptar_data",
]

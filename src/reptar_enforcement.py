"""
REPTAR Enforcement Module

Ensures REPTAR is used for ALL halftime predictions.
Monitors prediction calls and logs violations.

Usage:
    from src.reptar_enforcement import enforce_reptar_usage, log_reptar_violation
"""

import functools
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
import json

# Setup logging
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - REPTAR - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / 'reptar_enforcement.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger('REPTAR')

# Violation tracking
_violations = []


def log_reptar_violation(
    violation_type: str,
    details: str,
    severity: str = "WARNING",
    context: Optional[Dict[str, Any]] = None,
):
    """Log a REPTAR violation.

    Args:
        violation_type: Type of violation
        details: Details of violation
        severity: Severity level (INFO, WARNING, ERROR, CRITICAL)
        context: Additional context
    """
    violation = {
        "timestamp": datetime.now().isoformat(),
        "type": violation_type,
        "severity": severity,
        "details": details,
        "context": context or {},
    }

    _violations.append(violation)

    # Log to file
    log_msg = f"{violation_type}: {details}"
    if severity == "CRITICAL":
        logger.critical(log_msg)
    elif severity == "ERROR":
        logger.error(log_msg)
    elif severity == "WARNING":
        logger.warning(log_msg)
    else:
        logger.info(log_msg)

    # Save violations to file
    violations_file = Path("logs/reptar_violations.json")
    try:
        existing = []
        if violations_file.exists():
            with open(violations_file, 'r') as f:
                existing = json.load(f)

        existing.append(violation)

        with open(violations_file, 'w') as f:
            json.dump(existing, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save violations: {e}")


def enforce_reptar_usage(func):
    """Decorator to enforce REPTAR usage for halftime predictions.

    Usage:
        @enforce_reptar_usage
        def predict_halftime(...):
            # This function MUST use REPTAR
            pass
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Check if REPTAR is loaded
        try:
            from src.reptar import is_reptar_loaded
            if not is_reptar_loaded():
                log_reptar_violation(
                    violation_type="REPTAR_NOT_LOADED",
                    details=f"Function {func.__name__} called without REPTAR loaded",
                    severity="ERROR",
                    context={"function": func.__name__},
                )
                # Try to load
                from src.reptar import load_reptar_model
                load_reptar_model()
        except ImportError:
            log_reptar_violation(
                violation_type="REPTAR_IMPORT_ERROR",
                details=f"Failed to import REPTAR module in {func.__name__}",
                severity="CRITICAL",
                context={"function": func.__name__},
            )

        # Execute function
        result = func(*args, **kwargs)

        # Verify result uses REPTAR features
        if isinstance(result, dict):
            # Check for REPTAR signature
            if "reptar_version" not in result and "model" not in result:
                log_reptar_violation(
                    violation_type="MISSING_REPTAR_SIGNATURE",
                    details=f"Result from {func.__name__} missing REPTAR signature",
                    severity="WARNING",
                    context={"function": func.__name__},
                )

        return result

    return wrapper


def check_data_uses_reptar(data_path: str) -> bool:
    """Check if data path uses REPTAR data.

    Args:
        data_path: Path to data file

    Returns:
        True if data is REPTAR data
    """
    if "halftime_with_refined_temporal" in data_path:
        return True

    log_reptar_violation(
        violation_type="NON_REPTAR_DATA",
        details=f"Data path does not use REPTAR data: {data_path}",
        severity="WARNING",
        context={"data_path": data_path},
    )
    return False


def check_model_uses_reptar(model_name: str) -> bool:
    """Check if model name is REPTAR.

    Args:
        model_name: Name of model

    Returns:
        True if model is REPTAR
    """
    if model_name.upper() == "REPTAR":
        return True

    log_reptar_violation(
        violation_type="NON_REPTAR_MODEL",
        details=f"Model is not REPTAR: {model_name}",
        severity="WARNING",
        context={"model_name": model_name},
    )
    return False


def get_violations() -> list:
    """Get all REPTAR violations.

    Returns:
        List of violations
    """
    return _violations.copy()


def clear_violations():
    """Clear all REPTAR violations."""
    global _violations
    _violations = []


def report_violations() -> str:
    """Generate a report of all REPTAR violations.

    Returns:
        Report string
    """
    if not _violations:
        return "No REPTAR violations detected"

    report = [
        "=" * 80,
        "REPTAR VIOLATIONS REPORT",
        "=" * 80,
        f"Total violations: {len(_violations)}",
        "",
    ]

    for i, v in enumerate(_violations, 1):
        report.extend([
            f"Violation #{i}:",
            f"  Type: {v['type']}",
            f"  Severity: {v['severity']}",
            f"  Details: {v['details']}",
            f"  Time: {v['timestamp']}",
            "",
        ])

    return "\n".join(report)


__all__ = [
    "enforce_reptar_usage",
    "log_reptar_violation",
    "check_data_uses_reptar",
    "check_model_uses_reptar",
    "get_violations",
    "clear_violations",
    "report_violations",
]

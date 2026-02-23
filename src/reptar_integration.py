"""
REPTAR Integration for All Halftime Predictions

This module provides REPTAR integration for all halftime prediction scripts.
It ensures REPTAR is always used with the correct formula, data, and features.

Usage:
    from src.reptar_integration import ReptarIntegrator

    integrator = ReptarIntegrator()
    predictions = integrator.enrich_halftime_result(game_data)
"""

import logging
from typing import Any, Dict, Optional

from scipy.stats import norm

from src.reptar import (
    load_reptar_model,
    calculate_reptar_win_probability,
    is_reptar_loaded,
    ReptarModelNotLoadedError,
)
from src.reptar_enforcement import (
    enforce_reptar_usage,
    log_reptar_violation,
)

logger = logging.getLogger(__name__)


class ReptarIntegrator:
    """
    REPTAR Integrator - Ensures all halftime predictions use REPTAR.

    This class provides a unified interface for halftime predictions
    that enforces REPTAR usage and logs violations.
    """

    def __init__(self, auto_load: bool = True, strict: bool = True):
        """Initialize REPTAR Integrator.

        Args:
            auto_load: Whether to auto-load REPTAR model
            strict: Whether to raise errors on violations
        """
        self.auto_load = auto_load
        self.strict = strict
        self._loaded = False

        if auto_load:
            self._load_reptar()

    def _load_reptar(self):
        """Load REPTAR model."""
        if not is_reptar_loaded():
            try:
                load_reptar_model(validate=True, strict=self.strict)
                self._loaded = True
                logger.info("REPTAR loaded successfully")
            except Exception as e:
                log_reptar_violation(
                    violation_type="LOAD_FAILED",
                    details=f"Failed to load REPTAR: {e}",
                    severity="CRITICAL",
                )
                if self.strict:
                    raise
        else:
            self._loaded = True

    def assert_reptar_loaded(self):
        """Assert that REPTAR is loaded."""
        if not self._loaded:
            self._load_reptar()

        if not is_reptar_loaded():
            if self.strict:
                raise ReptarModelNotLoadedError(
                    "REPTAR must be loaded for halftime predictions"
                )
            else:
                log_reptar_violation(
                    violation_type="REPTAR_NOT_LOADED",
                    details="REPTAR not loaded for halftime prediction",
                    severity="ERROR",
                )

    @enforce_reptar_usage
    def calculate_win_probability(
        self,
        h1_margin: float,
        pred_h2_margin: float,
        sigma_h2_margin: float,
        sigma_k_margin: float = 3.0,
    ) -> float:
        """Calculate REPTAR win probability.

        This ensures the CORRECT formula is always used:
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
        return calculate_reptar_win_probability(
            h1_margin=h1_margin,
            pred_h2_margin=pred_h2_margin,
            sigma_h2_margin=sigma_h2_margin,
            sigma_k_margin=sigma_k_margin,
        )

    @enforce_reptar_usage
    def enrich_halftime_result(
        self,
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Enrich halftime prediction result with REPTAR win probability.

        Args:
            result: Halftime prediction result

        Returns:
            Enriched result with win probability
        """
        self.assert_reptar_loaded()

        # Extract required fields
        h1_home = result.get('h1_home', result.get('home_score', 0))
        h1_away = result.get('h1_away', result.get('away_score', 0))
        h1_margin = h1_home - h1_away

        # Get H2 margin prediction
        pred_2h_home = result.get('pred_2h_home', 0)
        pred_2h_away = result.get('pred_2h_away', 0)
        pred_h2_margin = pred_2h_home - pred_2h_away

        # Get sigma estimate
        margin_sd = result.get('margin_sd')
        if margin_sd is None:
            # Try q10/q90
            margin_q10 = result.get('margin_q10')
            margin_q90 = result.get('margin_q90')
            if margin_q10 is not None and margin_q90 is not None:
                margin_sd = (margin_q90 - margin_q10) / (2.0 * 1.2815515655)

        if margin_sd is None:
            # Default sigma estimate
            margin_sd = 10.0
            log_reptar_violation(
                violation_type="MISSING_SIGMA",
                details="No sigma estimate found, using default (10.0)",
                severity="WARNING",
            )

        # Calculate win probability using REPTAR formula
        home_win_prob = self.calculate_win_probability(
            h1_margin=h1_margin,
            pred_h2_margin=pred_h2_margin,
            sigma_h2_margin=margin_sd,
        )

        # Enrich result
        enriched = result.copy()
        enriched['home_win_prob'] = home_win_prob
        enriched['away_win_prob'] = 1.0 - home_win_prob
        enriched['reptar_version'] = '1.0.0'
        enriched['win_prob_method'] = 'REPTAR'

        return enriched


# Convenience functions

@enforce_reptar_usage
def calculate_reptar_win_prob_safe(
    h1_margin: float,
    pred_h2_margin: float,
    sigma_h2_margin: float,
    sigma_k_margin: float = 3.0,
) -> float:
    """Safe wrapper for REPTAR win probability calculation.

    This function ensures REPTAR is loaded and uses the correct formula.

    Args:
        h1_margin: First half margin (home - away)
        pred_h2_margin: Predicted second half margin
        sigma_h2_margin: Raw sigma for H2 margin
        sigma_k_margin: Calibration factor (default 3.0)

    Returns:
        Win probability (0-1)
    """
    integrator = ReptarIntegrator(auto_load=True, strict=False)
    return integrator.calculate_win_probability(
        h1_margin=h1_margin,
        pred_h2_margin=pred_h2_margin,
        sigma_h2_margin=sigma_h2_margin,
        sigma_k_margin=sigma_k_margin,
    )


@enforce_reptar_usage
def enrich_halftime_prediction(
    result: Dict[str, Any],
) -> Dict[str, Any]:
    """Enrich halftime prediction with REPTAR win probability.

    This is a convenience function for one-off enrichment.

    Args:
        result: Halftime prediction result

    Returns:
        Enriched result with win probability
    """
    integrator = ReptarIntegrator(auto_load=True, strict=False)
    return integrator.enrich_halftime_result(result)


__all__ = [
    'ReptarIntegrator',
    'calculate_reptar_win_prob_safe',
    'enrich_halftime_prediction',
]

from __future__ import annotations

"""Market-implied probability estimation (prototype).

HARD RULE:
- Uses only local composite odds (pass snapshots in from local client).
- Does NOT use any model probability.

This module implements the minimal math needed for v0 tracking:
- De-vig two-sided odds into a fair probability at the current market line.
- Infer a market-implied Normal(mu, sigma) for the underlying outcome.
- Convert that into probability that the ORIGINAL ticket wins.

Caveats:
- Normal assumption is a simplification.
- Sigma is fixed per bet type in v0.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from src.betting import normal_cdf

from .devig import devig_two_sided
from .math.norm import ppf_standard_normal


@dataclass(frozen=True)
class SigmaConfig:
    spread_margin_sd: float = 12.0
    total_sd: float = 14.0


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def infer_margin_mu_from_market(*, spread_home: float, p_home_cover: float, sd: float) -> float:
    """Infer mu for margin M=home-away given market home spread and fair prob home covers.

    Home covers when: M > -spread_home

    p = 1 - Phi(((-spread_home) - mu)/sd)
    => Phi(((-spread_home) - mu)/sd) = 1 - p
    => z = Phi^{-1}(1-p)
    => mu = (-spread_home) - sd*z
    """

    p = _clamp01(p_home_cover)
    # Avoid infs
    p = min(0.9999, max(0.0001, p))
    z = ppf_standard_normal(1.0 - p)
    return (-float(spread_home)) - float(sd) * z


def infer_total_mu_from_market(*, total_line: float, p_over: float, sd: float) -> float:
    """Infer mu for total points given market total line and fair prob over.

    p_over = 1 - Phi((total_line - mu)/sd)
    => Phi((total_line - mu)/sd) = 1 - p_over
    => z = Phi^{-1}(1-p_over)
    => mu = total_line - sd*z
    """

    p = _clamp01(p_over)
    p = min(0.9999, max(0.0001, p))
    z = ppf_standard_normal(1.0 - p)
    return float(total_line) - float(sd) * z


def prob_ticket_spread_hits(
    *,
    ticket_team: str,
    home_team: str,
    away_team: str,
    ticket_line: float,
    mu_margin: float,
    sd_margin: float,
) -> float:
    """Probability a spread ticket hits given margin distribution.

    margin M = home - away ~ Normal(mu_margin, sd_margin)

    If ticket is on HOME at line h:
      wins when M + h > 0  => M > -h

    If ticket is on AWAY at line a:
      wins when (away - home) + a > 0
           => -M + a > 0
           => M < a

    Args:
        ticket_line: the line shown next to the *ticket team* (signed)
    """

    team = ticket_team.upper().strip()
    home = home_team.upper().strip()
    away = away_team.upper().strip()

    mu = float(mu_margin)
    sd = float(sd_margin)
    if sd <= 0:
        return 0.5

    if team == home:
        threshold = -float(ticket_line)
        return 1.0 - normal_cdf(threshold, mu=mu, sigma=sd)

    if team == away:
        threshold = float(ticket_line)
        return normal_cdf(threshold, mu=mu, sigma=sd)

    # Unknown mapping
    return 0.5


def prob_ticket_total_hits(*, ticket_side: str, ticket_line: float, mu_total: float, sd_total: float) -> float:
    """Probability a total ticket hits given total distribution."""

    side = ticket_side.upper().strip()
    mu = float(mu_total)
    sd = float(sd_total)
    if sd <= 0:
        return 0.5

    if side == "OVER":
        return 1.0 - normal_cdf(float(ticket_line), mu=mu, sigma=sd)
    if side == "UNDER":
        return normal_cdf(float(ticket_line), mu=mu, sigma=sd)

    return 0.5


@dataclass(frozen=True)
class MarketImpliedResult:
    p_hit: float
    mu: float
    sd: float
    notes: tuple[str, ...] = ()


def estimate_spread_from_snapshot(
    *,
    home_team: str,
    away_team: str,
    ticket_team: str,
    ticket_line: float,
    spread_home: float,
    spread_home_odds: int,
    spread_away_odds: int,
    sigma_cfg: SigmaConfig | None = None,
) -> MarketImpliedResult:
    cfg = sigma_cfg or SigmaConfig()
    sd = float(cfg.spread_margin_sd)

    fair = devig_two_sided(odds_a=int(spread_home_odds), odds_b=int(spread_away_odds))
    p_home_cover = fair.p_side_a

    mu = infer_margin_mu_from_market(spread_home=float(spread_home), p_home_cover=p_home_cover, sd=sd)
    p_hit = prob_ticket_spread_hits(
        ticket_team=ticket_team,
        home_team=home_team,
        away_team=away_team,
        ticket_line=float(ticket_line),
        mu_margin=mu,
        sd_margin=sd,
    )

    return MarketImpliedResult(
        p_hit=_clamp01(p_hit),
        mu=mu,
        sd=sd,
        notes=(f"fair_p_home_cover={p_home_cover:.3f}",),
    )


def estimate_total_from_snapshot(
    *,
    ticket_side: str,
    ticket_line: float,
    total_points: float,
    total_over_odds: int,
    total_under_odds: int,
    sigma_cfg: SigmaConfig | None = None,
) -> MarketImpliedResult:
    cfg = sigma_cfg or SigmaConfig()
    sd = float(cfg.total_sd)

    fair = devig_two_sided(odds_a=int(total_over_odds), odds_b=int(total_under_odds))
    p_over = fair.p_side_a
    mu = infer_total_mu_from_market(total_line=float(total_points), p_over=p_over, sd=sd)

    p_hit = prob_ticket_total_hits(
        ticket_side=ticket_side,
        ticket_line=float(ticket_line),
        mu_total=mu,
        sd_total=sd,
    )

    return MarketImpliedResult(
        p_hit=_clamp01(p_hit),
        mu=mu,
        sd=sd,
        notes=(f"fair_p_over={p_over:.3f}",),
    )

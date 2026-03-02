"""MAXIMUS pregame automation cycle.

This module is designed for long-running stability:
- Idempotent DB writes (never duplicate pregame predictions).
- One-game failure doesn't kill the whole cycle.
- No Discord posting by default (wire later).

MAXIMUS = Pregame.
REPTAR = Halftime.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from datetime import timezone

import pandas as pd

from dashboard.backend.database import (
    BettingRecommendation,
    BetType,
    Game,
    Prediction,
    PredictionStatus,
    SessionLocal,
    TriggerType as DBTriggerType,
)
from src.automation.post_generator import PostGenerator
from src.data.pregame_features import PregameFeatureContext, build_pregame_features
from src.models.pregame import get_pregame_model
from src.odds import OddsAPIError, fetch_nba_odds_snapshot
from src.schedule import fetch_schedule
from src.utils.league_time import league_day_str

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PregameCycleConfig:
    lookahead_hours: float = 12.0
    min_minutes_before_tip: float = 15.0
    include_betting: bool = True
    enabled: bool = True


def _parse_game_datetime(schedule_game: dict) -> Optional[datetime]:
    """Parse ESPN schedule ISO datetime if present."""
    dt_str = schedule_game.get("date_time")
    if not dt_str:
        return None
    try:
        # ESPN: 2026-02-28T00:00Z
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception:
        return None


def run_pregame_cycle(*, cfg: PregameCycleConfig) -> int:
    """Run one MAXIMUS pregame cycle.

    Returns number of new predictions created.
    """

    if not cfg.enabled:
        return 0

    model = get_pregame_model()
    if model is None or not model._loaded:
        logger.warning("MAXIMUS pregame model not loaded; skipping cycle")
        return 0

    date_str = league_day_str()
    logger.info(f"MAXIMUS pregame cycle start date={date_str}")

    schedule = fetch_schedule(date_str)
    games = schedule.get("games", [])
    logger.info(f"MAXIMUS schedule games={len(games)} date={date_str}")

    if not games:
        return 0

    now_utc = datetime.now(timezone.utc)
    created = 0

    for idx, g in enumerate(games, start=1):
        nba_id = g.get("nba_id")
        if not nba_id:
            continue

        game_dt = _parse_game_datetime(g)
        if game_dt is None:
            continue

        # Skip games too far away
        if game_dt.astimezone(timezone.utc) > (now_utc + timedelta(hours=cfg.lookahead_hours)):
            continue

        # Skip games too close / already started
        minutes_to_tip = (game_dt.astimezone(timezone.utc) - now_utc).total_seconds() / 60.0
        if minutes_to_tip < cfg.min_minutes_before_tip:
            continue

        home_tri = (g.get("home_team") or "").upper()
        away_tri = (g.get("away_team") or "").upper()
        if not home_tri or not away_tri:
            continue

        if idx == 1:
            logger.info("MAXIMUS building first game prediction...")

        db = SessionLocal()
        try:
            game = db.query(Game).filter(Game.nba_id == nba_id).first()
            if not game:
                game = Game(
                    nba_id=nba_id,
                    game_date=game_dt,
                    home_team=home_tri,
                    away_team=away_tri,
                    home_team_name=None,
                    away_team_name=None,
                    game_status="Scheduled",
                )
                db.add(game)
                db.commit()
                db.refresh(game)

            # Idempotency: skip if already have pregame prediction
            existing = (
                db.query(Prediction)
                .filter(Prediction.game_id == game.id, Prediction.trigger_type == DBTriggerType.PREGAME)
                .first()
            )
            if existing:
                continue

            # Build features
            feats_raw = None

            if len(getattr(model, "features", []) or []) >= 54:
                from src.data.maximus_features import (
                    MaximusFeatureContext,
                    build_maximus_features,
                    season_str_from_dt,
                )

                feats_raw = build_maximus_features(
                    MaximusFeatureContext(
                        game_id=nba_id,
                        home_tricode=home_tri,
                        away_tricode=away_tri,
                        game_datetime_utc=game_dt.astimezone(timezone.utc),
                        season=season_str_from_dt(game_dt.astimezone(timezone.utc)),
                    )
                )
            else:
                ctx = PregameFeatureContext(
                    game_id=nba_id,
                    home_tricode=home_tri,
                    away_tricode=away_tri,
                    game_datetime=game_dt,
                )
                feats_raw = build_pregame_features(ctx)

            from src.automation.maximus_safety import (
                safety_config_from_env,
                clamp_features,
                allow_betting_recs,
            )

            safety_cfg = safety_config_from_env()
            feats, clamped_info = clamp_features(feats_raw, cfg=safety_cfg)
            if clamped_info:
                logger.warning(
                    f"MAXIMUS safety: clamped {len(clamped_info)} feature(s) for {away_tri}@{home_tri}: {clamped_info}"
                )

            pred = model.predict(feats, game_id=nba_id)
            if pred is None:
                continue

            # Normalize to common dict format used by PostGenerator
            pred_dict = {
                "game_id": nba_id,
                "pred_final_total": float(pred.total_mean),
                "pred_final_margin": float(pred.margin_mean),
                "home_win_prob": float(pred.home_win_prob),
                "total_sd": float(pred.total_sd),
                "margin_sd": float(pred.margin_sd),
                "total_q10": float(pred.total_q10),
                "total_q90": float(pred.total_q90),
                "margin_q10": float(pred.margin_q10),
                "margin_q90": float(pred.margin_q90),
                "model_name": "MAXIMUS",
            }

            betting_allowed = allow_betting_recs(
                pred_total=pred_dict["pred_final_total"],
                pred_margin=pred_dict["pred_final_margin"],
                clamped_info=clamped_info,
                cfg=safety_cfg,
            )

            if not betting_allowed:
                logger.warning(
                    f"MAXIMUS safety: betting disabled for {away_tri}@{home_tri} "
                    f"(total={pred_dict['pred_final_total']:.1f}, margin={pred_dict['pred_final_margin']:+.1f}, clamped={len(clamped_info)})"
                )

            # Odds snapshot (pregame via ESPN adapter)
            odds = None
            try:
                snap = fetch_nba_odds_snapshot(home_name=home_tri, away_name=away_tri)
                odds = {
                    "total_points": snap.total_points,
                    "total_over_odds": snap.total_over_odds,
                    "total_under_odds": snap.total_under_odds,
                    "spread_home": snap.spread_home,
                    "spread_home_odds": snap.spread_home_odds,
                    "spread_away_odds": snap.spread_away_odds,
                    "moneyline_home": snap.moneyline_home,
                    "moneyline_away": snap.moneyline_away,
                    "team_total_home": snap.team_total_home,
                    "team_total_home_over_odds": snap.team_total_home_over_odds,
                    "team_total_home_under_odds": snap.team_total_home_under_odds,
                    "team_total_away": snap.team_total_away,
                    "team_total_away_over_odds": snap.team_total_away_over_odds,
                    "team_total_away_under_odds": snap.team_total_away_under_odds,
                    "bookmaker": snap.bookmaker,
                }
            except OddsAPIError as e:
                logger.info(f"Pregame odds unavailable for {away_tri}@{home_tri}: {e}")

            # Recommendations (guarded by safety)
            recs = []
            passed = []
            if betting_allowed and cfg.include_betting:
                post_gen = PostGenerator(include_betting=True)
                recs, passed = post_gen.create_recommendations_from_prediction(
                    pred_dict,
                    odds,
                    home_team=home_tri,
                    away_team=away_tri,
                )

            # Save prediction
            p = Prediction(
                game_id=game.id,
                trigger_type=DBTriggerType.PREGAME,
                pred_total=float(pred.total_mean),
                pred_margin=float(pred.margin_mean),
                home_win_prob=float(pred.home_win_prob),
                total_q10=float(pred.total_q10),
                total_q90=float(pred.total_q90),
                margin_q10=float(pred.margin_q10),
                margin_q90=float(pred.margin_q90),
                status=PredictionStatus.PENDING,
                posted_to_discord=False,
            )
            db.add(p)
            db.commit()
            db.refresh(p)

            # Save recommended bets (both recommended and passed for audit)
            def to_bet_type(bt: str) -> BetType:
                bt_l = bt.strip().lower()
                if bt_l.startswith("total"):
                    return BetType.TOTAL
                if bt_l.startswith("spread"):
                    return BetType.SPREAD
                if bt_l.startswith("money") or bt_l == "ml":
                    return BetType.MONEYLINE
                if "team" in bt_l:
                    return BetType.TEAM_TOTAL
                return BetType.TOTAL

            for b in recs + passed:
                bt_enum = to_bet_type(b.bet_type)

                pick_txt = b.pick
                if bt_enum == BetType.TEAM_TOTAL:
                    # IMPORTANT: bet_resolver expects team identifier in pick text.
                    team = (b.team_name or "").strip() or (home_tri if "HOME" in (b.pick or "").upper() else away_tri)
                    if b.line is not None:
                        pick_txt = f"{team} {b.pick} {float(b.line):.1f}"
                    else:
                        pick_txt = f"{team} {b.pick}"

                br = BettingRecommendation(
                    prediction_id=p.id,
                    bet_type=bt_enum,
                    pick=pick_txt,
                    line=b.line,
                    odds=b.odds,
                    edge=float(b.edge),
                    probability=float(b.probability),
                    confidence_tier=b.confidence_tier,
                    model_prediction=b.model_prediction,
                )
                db.add(br)

            db.commit()
            created += 1

            logger.info(f"MAXIMUS pregame saved: {away_tri}@{home_tri} nba_id={nba_id} pred_id={p.id}")

        except Exception as e:
            logger.exception(f"MAXIMUS pregame cycle error for nba_id={nba_id}: {e}")
        finally:
            db.close()

    return created


__all__ = [
    "PregameCycleConfig",
    "run_pregame_cycle",
]

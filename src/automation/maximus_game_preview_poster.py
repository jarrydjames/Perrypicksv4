"""MAXIMUS Game Preview Poster (1-hour-before tip)

Posts a richer per-game pregame analysis ~1 hour before tip:
- matchup + tip time
- projected final, winner, total, margin, win prob
- UPDATED odds at posting time
- betting recommendations with probabilities

Routing:
- MAIN -> DISCORD_MAXIMUS_PREGAME_WEBHOOK
- Priority bucket -> DISCORD_HIGH_CONFIDENCE_WEBHOOK
- SGP -> DISCORD_SGP_WEBHOOK

Idempotency:
- Uses `.cache/maximus_preview_posted_pred_<id>.marker` (no DB migration).

NOTE:
- This is different from the daily summary post.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Tuple

from dashboard.backend.database import (
    BettingRecommendation as DBBetRec,
    Game,
    Prediction,
    SessionLocal,
    TriggerType,
)
from src.automation.channel_router import ChannelRouter, ChannelType
from src.automation.post_generator import PostGenerator
from src.utils.datetime_utils import as_utc
from src.utils.league_time import format_league_dt
from src.odds import OddsAPIError, fetch_nba_odds_snapshot

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreviewConfig:
    enabled: bool
    minutes_before_tip: int = 60
    grace_seconds: int = 120
    max_posts_per_tick: int = 3


def _marker_path(pred_id: int) -> Path:
    d = Path(".cache")
    d.mkdir(exist_ok=True)
    return d / f"maximus_preview_posted_pred_{pred_id}.marker"


def _rec_rows_to_dicts(recs: List[DBBetRec]) -> List[dict]:
    out: List[dict] = []
    for r in recs:
        out.append(
            {
                "bet_type": str(r.bet_type.value if hasattr(r.bet_type, "value") else r.bet_type).lower(),
                "pick": r.pick,
                "line": r.line,
                "odds": r.odds,
                "edge": r.edge,
                "probability": r.probability,
                "confidence_tier": r.confidence_tier,
            }
        )
    return out


class MaximusGamePreviewPoster:
    def __init__(self, cfg: PreviewConfig):
        self._cfg = cfg

    @staticmethod
    def from_env() -> PreviewConfig:
        enabled = os.environ.get("MAXIMUS_GAME_PREVIEW_ENABLED", "true").lower() in (
            "true",
            "1",
            "yes",
        )
        minutes = int(os.environ.get("MAXIMUS_GAME_PREVIEW_MINUTES_BEFORE_TIP", "60"))
        grace_s = int(os.environ.get("MAXIMUS_GAME_PREVIEW_GRACE_S", "120"))
        max_per = int(os.environ.get("MAXIMUS_GAME_PREVIEW_MAX_PER_TICK", "3"))
        return PreviewConfig(
            enabled=enabled,
            minutes_before_tip=max(0, minutes),
            grace_seconds=max(1, grace_s),
            max_posts_per_tick=max(1, max_per),
        )

    def post_due_previews(self) -> int:
        if not self._cfg.enabled:
            return 0

        pregame_webhook = os.environ.get("DISCORD_MAXIMUS_PREGAME_WEBHOOK", "").strip()
        if not pregame_webhook:
            logger.warning("MAXIMUS preview: DISCORD_MAXIMUS_PREGAME_WEBHOOK missing")
            return 0

        router = ChannelRouter(
            main_webhook=pregame_webhook,
            high_confidence_webhook=os.environ.get("DISCORD_HIGH_CONFIDENCE_WEBHOOK"),
            sgp_webhook=os.environ.get("DISCORD_SGP_WEBHOOK"),
            post_to_main_always=True,
        )

        now = datetime.now(timezone.utc)
        target_min = self._cfg.minutes_before_tip
        # Coarse SQL window just to avoid scanning everything
        lo = now + timedelta(minutes=target_min) - timedelta(minutes=2)
        hi = now + timedelta(minutes=target_min) + timedelta(minutes=2)

        db = SessionLocal()
        try:
            rows: List[Tuple[Prediction, Game]] = (
                db.query(Prediction, Game)
                .join(Game)
                .filter(
                    Prediction.trigger_type == TriggerType.PREGAME,
                    Game.game_status == "Scheduled",
                    Game.game_date >= lo,
                    Game.game_date <= hi,
                )
                .order_by(Game.game_date.asc())
                .all()
            )

            posted = 0
            post_gen = PostGenerator(include_betting=True)

            for pred, game in rows:
                if posted >= self._cfg.max_posts_per_tick:
                    break
                if _marker_path(pred.id).exists():
                    continue

                from src.utils.datetime_utils import as_utc_from_league_local

                game_dt_utc = as_utc_from_league_local(game.game_date)

                # Exact due-time gate: only post when we're ~60 minutes before tip
                due_at = game_dt_utc - timedelta(minutes=target_min)
                if now < due_at:
                    continue
                if now > (due_at + timedelta(seconds=self._cfg.grace_seconds)):
                    continue

                home = str(game.home_team)
                away = str(game.away_team)

                tip_str = format_league_dt(
                    game_dt_utc,
                    fmt="%Y-%m-%d %I:%M %p %Z",
                )

                # Fetch updated odds at posting time
                odds = None
                odds_available = True
                try:
                    snap = fetch_nba_odds_snapshot(home_name=home, away_name=away)
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
                    odds_available = False
                    logger.info(f"MAXIMUS preview odds unavailable for {away}@{home}: {e}")

                prediction_dict = {
                    "pred_final_total": float(pred.pred_total or 0.0),
                    "pred_final_margin": float(pred.pred_margin or 0.0),
                    "home_win_prob": float(pred.home_win_prob or 0.5),
                    "total_sd": 10.87,
                    "margin_sd": 7.76,
                    "total_q10": pred.total_q10,
                    "total_q90": pred.total_q90,
                    "margin_q10": pred.margin_q10,
                    "margin_q90": pred.margin_q90,
                    "model_name": "MAXIMUS",
                }

                # Recommendations for routing logic (priority/SGP)
                rec_rows = (
                    db.query(DBBetRec)
                    .filter(DBBetRec.prediction_id == pred.id)
                    .order_by(DBBetRec.probability.desc())
                    .all()
                )
                rec_dicts = _rec_rows_to_dicts(rec_rows)

                # Recompute recommendations with UPDATED odds at posting time
                recs_now, passed_now = post_gen.create_recommendations_from_prediction(
                    prediction_dict,
                    odds,
                    home_team=home,
                    away_team=away,
                )

                # Generate rich pregame post (includes bets section)
                gen = post_gen.generate_pregame_post(
                    prediction=prediction_dict,
                    home_team=home,
                    away_team=away,
                    game_time=tip_str,
                    recommendations=recs_now,
                    passed_bets=passed_now,
                    odds_available=odds_available,
                )

                content = gen.content[:1900]

                prediction_for_router = {
                    "away_team": away,
                    "home_team": home,
                    "pred_total": float(pred.pred_total or 0.0),
                    "pred_margin": float(pred.pred_margin or 0.0),
                    "home_win_prob": float(pred.home_win_prob or 0.5),
                    "game_datetime": tip_str,
                    "model_name": "MAXIMUS",
                }

                results = router.route_prediction(
                    content=content,
                    prediction=prediction_for_router,
                    recommendations=rec_dicts,
                )

                if not any(r.success for r in results.values()):
                    logger.error(f"MAXIMUS preview failed to post for pred_id={pred.id}")
                    continue

                # Save parlay tracking if SGP posted
                sgp_res = results.get(ChannelType.SGP)
                if sgp_res and sgp_res.success:
                    try:
                        sgp_picks = router._get_sgp_picks(rec_dicts, home, away)
                        if len(sgp_picks) >= 2:
                            from src.automation.report_card import save_parlay_from_recommendations

                            combined_prob = router._calculate_combined_probability(sgp_picks)
                            save_parlay_from_recommendations(
                                game_id=game.id,
                                prediction_id=pred.id,
                                recommendations=sgp_picks,
                                combined_probability=combined_prob,
                            )
                    except Exception:
                        logger.exception("Failed to save MAXIMUS preview parlay")

                _marker_path(pred.id).write_text(now.isoformat(), encoding="utf-8")
                posted += 1

            return posted
        finally:
            db.close()

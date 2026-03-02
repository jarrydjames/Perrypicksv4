"""MAXIMUS Pregame Discord Posting

Keep this separate from `start.py` because that file is already doing *way* too much.
(SOLID: single responsibility, please and thank you.)

This module:
- finds MAXIMUS pregame predictions that haven't been posted
- formats a Discord message
- posts via a dedicated webhook
- marks posted_to_discord + status

Feature-flagged via env var:
- MAXIMUS_PREGAME_POSTING_ENABLED=true
- DISCORD_MAXIMUS_PREGAME_WEBHOOK=https://discord.com/api/webhooks/...

We intentionally keep formatting simple and avoid embedding brittle odds logic here.
Odds + recs are already stored at prediction time by MAXIMUS cycle.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from src.automation.discord_client import DiscordClient
from src.automation.channel_router import ChannelRouter, ChannelType
from src.utils.datetime_utils import as_utc_from_league_local

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MaximusPosterConfig:
    enabled: bool
    webhook_url: str
    username: str = "MAXIMUS"
    max_posts_per_tick: int = 3


def _odds_str(odds: Optional[int]) -> str:
    if odds is None:
        return ""
    try:
        o = int(odds)
    except Exception:
        return ""
    return f" ({o:+d})" if o > 0 else f" ({o})"


def _fmt_line(line: Optional[float]) -> str:
    if line is None:
        return ""
    try:
        return f" {float(line):.1f}"
    except Exception:
        return ""


def _format_rec_pick(*, bet_type: str, pick: str, line: Optional[float], home: str, away: str) -> str:
    """Human-friendly pick formatting for Discord.

    The DB stores compact picks like OVER/UNDER/HOME/AWAY.
    We expand them so humans don't have to decode.
    """

    bt = (bet_type or "").lower()
    pk = (pick or "").strip().upper()

    if bt == "moneyline":
        team = home if pk == "HOME" else away if pk == "AWAY" else pk
        return f"{team} ML"

    if bt == "total":
        side = pk if pk in ("OVER", "UNDER") else pk
        ln = _fmt_line(line)
        return f"Game Total {side}{ln}".strip()

    if bt == "spread":
        team = home if pk == "HOME" else away if pk == "AWAY" else pk
        if line is None:
            return f"{team} Spread"
        try:
            # line might already be signed; keep it.
            return f"{team} {float(line):+0.1f}"
        except Exception:
            return f"{team} Spread"

    if bt == "team_total":
        # Common patterns: "GSW OVER" or "OVER".
        parts = pk.split()
        if len(parts) >= 2 and parts[0] in (home, away) and parts[1] in ("OVER", "UNDER"):
            team = parts[0]
            side = parts[1]
            return f"{team} Team Total {side}{_fmt_line(line)}".strip()

        side = pk if pk in ("OVER", "UNDER") else pk
        return f"Team Total {side}{_fmt_line(line)}".strip()

    # Fallback
    return f"{pk}{_fmt_line(line)}".strip()


def _format_maximus_pregame_message(
    *,
    away: str,
    home: str,
    game_dt: datetime,
    pred_total: float,
    pred_margin: float,
    home_win_prob: float,
    rec_lines: List[str],
) -> str:
    # Project final
    pred_home = (pred_total + pred_margin) / 2.0
    pred_away = (pred_total - pred_margin) / 2.0

    if pred_margin > 0:
        winner = home
        winp = home_win_prob
    else:
        winner = away
        winp = 1.0 - home_win_prob

    tip = game_dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines: List[str] = [
        "🧠 MAXIMUS PREGAME",
        "",
        f"**{away} @ {home}** | Tip: {tip}",
        "",
        "---",
        "",
        "**MODEL PROJECTION**",
        f"Final: {away} {pred_away:.0f} - {home} {pred_home:.0f}",
        f"Total: {pred_total:.1f} | Margin: {winner} {abs(pred_margin):.1f}",
        f"Win Probability: {winner} {winp:.0%}",
    ]

    if rec_lines:
        lines.extend(["", "---", "", "**TOP BETS**"])
        lines.extend(rec_lines)

    # Discord cap safety (DiscordClient also caps, but be nice)
    return "\n".join(lines)[:1900]


class MaximusPregamePoster:
    def __init__(self, cfg: MaximusPosterConfig):
        self._cfg = cfg

    @staticmethod
    def from_env() -> MaximusPosterConfig:
        enabled = os.environ.get("MAXIMUS_PREGAME_POSTING_ENABLED", "false").lower() in (
            "true",
            "1",
            "yes",
        )
        webhook = os.environ.get("DISCORD_MAXIMUS_PREGAME_WEBHOOK", "").strip()
        max_per_tick = int(os.environ.get("MAXIMUS_PREGAME_POST_MAX_PER_TICK", "3"))
        return MaximusPosterConfig(
            enabled=enabled,
            webhook_url=webhook,
            max_posts_per_tick=max(1, max_per_tick),
        )

    def post_pending(self) -> int:
        if not self._cfg.enabled:
            return 0
        if not self._cfg.webhook_url:
            logger.error(
                "MAXIMUS posting enabled but DISCORD_MAXIMUS_PREGAME_WEBHOOK is missing"
            )
            return 0

        # Local import to avoid import-time DB coupling
        from dashboard.backend.database import (
            BettingRecommendation,
            Game,
            Prediction,
            PredictionStatus,
            SessionLocal,
            TriggerType,
        )

        now_utc = datetime.now(timezone.utc)
        min_minutes = float(os.environ.get("MAXIMUS_PREGAME_POST_MIN_MINUTES_BEFORE_TIP", "10"))
        max_tip_utc = now_utc + timedelta(minutes=min_minutes)

        db = SessionLocal()
        try:
            # NOTE: Game.game_date is stored as naive local time in our DB.
            # Do NOT compare it directly to UTC in SQL (you'll filter out everything).
            candidates = (
                db.query(Prediction, Game)
                .join(Game)
                .filter(
                    Prediction.trigger_type == TriggerType.PREGAME,
                    Prediction.posted_to_discord == False,  # noqa: E712
                    Game.game_status == "Scheduled",
                )
                .order_by(Game.game_date.asc())
                .limit(50)
                .all()
            )

            pending = []
            for pred, game in candidates:
                tip_utc = as_utc_from_league_local(game.game_date)
                if tip_utc <= max_tip_utc:
                    pending.append((pred, game))
                if len(pending) >= self._cfg.max_posts_per_tick:
                    break

            if not pending:
                return 0

            router = ChannelRouter(
                main_webhook=self._cfg.webhook_url,
                high_confidence_webhook=os.environ.get("DISCORD_HIGH_CONFIDENCE_WEBHOOK"),
                sgp_webhook=os.environ.get("DISCORD_SGP_WEBHOOK"),
                post_to_main_always=True,
            )
            posted = 0

            for pred, game in pending:
                try:
                    # Pull recs (already computed at MAXIMUS cycle time)
                    rec_rows = (
                        db.query(BettingRecommendation)
                        .filter(BettingRecommendation.prediction_id == pred.id)
                        .order_by(BettingRecommendation.probability.desc())
                        .all()
                    )

                    rec_lines: List[str] = []
                    rec_dicts: List[dict] = []
                    for r in rec_rows[:3]:
                        bt = str(getattr(r.bet_type, "value", r.bet_type) or "")
                        pretty_pick = _format_rec_pick(
                            bet_type=bt,
                            pick=str(r.pick or ""),
                            line=(float(r.line) if r.line is not None else None),
                            home=str(game.home_team),
                            away=str(game.away_team),
                        )
                        rec_lines.append(
                            f"• {pretty_pick}{_odds_str(r.odds)} | Prob {r.probability:.0%} | Edge {r.edge:+.1f}"
                        )

                    # For router logic (priority bucket + SGP), include all recs
                    for r in rec_rows:
                        rec_dicts.append(
                            {
                                "bet_type": str(getattr(r.bet_type, "value", r.bet_type) or "").lower(),
                                "pick": r.pick,
                                "line": r.line,
                                "odds": r.odds,
                                "edge": r.edge,
                                "probability": r.probability,
                                "confidence_tier": r.confidence_tier,
                            }
                        )

                    content = _format_maximus_pregame_message(
                        away=str(game.away_team),
                        home=str(game.home_team),
                        game_dt=game.game_date,
                        pred_total=float(pred.pred_total),
                        pred_margin=float(pred.pred_margin),
                        home_win_prob=float(pred.home_win_prob),
                        rec_lines=rec_lines,
                    )

                    tip_str = as_utc_from_league_local(game.game_date).strftime("%Y-%m-%d %H:%M UTC")
                    prediction_for_router = {
                        "away_team": str(game.away_team),
                        "home_team": str(game.home_team),
                        "pred_total": float(pred.pred_total),
                        "pred_margin": float(pred.pred_margin),
                        "home_win_prob": float(pred.home_win_prob),
                        "game_datetime": tip_str,
                        "model_name": "MAXIMUS",
                    }

                    results = router.route_prediction(
                        content=content,
                        prediction=prediction_for_router,
                        recommendations=rec_dicts,
                    )

                    any_success = any(res.success for res in results.values())
                    if not any_success:
                        err = next((res.error for res in results.values() if not res.success), None)
                        raise RuntimeError(err or "discord post failed")

                    # Save parlay tracking if SGP posted successfully
                    sgp_res = results.get(ChannelType.SGP)
                    if sgp_res and sgp_res.success:
                        try:
                            # Build SGP legs using the same router logic
                            sgp_picks = router._get_sgp_picks(
                                rec_dicts,
                                prediction_for_router["home_team"],
                                prediction_for_router["away_team"],
                            )
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
                            logger.exception("Failed to save MAXIMUS parlay tracking")

                    pred.posted_to_discord = True
                    pred.status = PredictionStatus.POSTED
                    db.add(pred)
                    db.commit()
                    posted += 1
                except Exception as e:
                    db.rollback()
                    logger.exception(
                        f"MAXIMUS pregame post failed pred_id={getattr(pred, 'id', None)}: {e}"
                    )
                    try:
                        pred.status = PredictionStatus.FAILED
                        db.add(pred)
                        db.commit()
                    except Exception:
                        db.rollback()

            return posted
        finally:
            db.close()

"""Prototype sidecar: market-implied tracking for halftime bets.

Option 2: posts standalone tracker messages to DISCORD_LIVE_TRACKING_WEBHOOK.
Option A: edits the same message continuously.

HARD RULE:
- Uses local composite odds only.
- Does NOT use model probabilities.

This is prototype-grade: fixed sigmas, basic trend.

Start manually:
  .venv/bin/python run_market_tracking.py

Stop:
  kill <pid>
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Dict, Optional, Tuple

from dotenv import load_dotenv
from sqlalchemy.exc import OperationalError

# Ensure we import from THIS repo (v5), not a sibling checkout (v4).
REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from dashboard.backend.database import (
    BettingRecommendation,
    BetStatus,
    Game,
    Prediction,
    SessionLocal,
    TriggerType,
    MarketTrackingMessage,
    MarketTrackingPoint,
)

from src.market_likelihood.market_data import LocalOddsQuery, fetch_local_snapshot
from src.market_likelihood.market_implied import (
    SigmaConfig,
    estimate_spread_from_snapshot,
    estimate_total_from_snapshot,
)
from src.market_likelihood.state import StateTracker, TierPolicy, tier_for_p
from src.market_likelihood.types import ProbabilityEstimate
from src.market_likelihood.tracker_view import build_tracking_embed, build_final_embed
from src.automation.bet_resolver import resolve_spread_bet, resolve_total_bet
from src.market_likelihood.discord_adapter import DiscordAdapterConfig, MarketDiscordPublisher

logger = logging.getLogger("market-tracking")

STALE_ODDS_SECONDS = int(os.environ.get("MARKET_TRACK_STALE_ODDS_SECONDS", "300"))

MAX_NEW_POSTS_PER_CYCLE = int(os.environ.get("MARKET_TRACK_MAX_NEW_POSTS_PER_CYCLE", "3"))

HEARTBEAT_PATH = Path(".market_tracking.heartbeat")


@dataclass(frozen=True)
class RunnerConfig:
    poll_seconds: int = 30
    edit_seconds: int = 60
    lookback_hours: int = 6

    # Only track bets whose recommendation probability >= threshold
    min_rec_prob: float = 0.72

    # Track only these bet types
    track_spread: bool = True
    track_total: bool = True

OLD_CACHE_PATH = Path(".cache/market_tracking_message_ids.json")


def _bootstrap_tracking_messages_from_cache(db) -> None:
    """Best-effort migration from old JSON cache into DB.

    This prevents duplicate tracker posts after upgrading to DB-backed idempotency.
    Safe to run repeatedly.
    """

    if not OLD_CACHE_PATH.exists():
        return

    try:
        raw = json.loads(OLD_CACHE_PATH.read_text())
    except Exception:
        logger.info("failed to read old market tracking cache; skipping bootstrap")
        return

    if not isinstance(raw, dict):
        return

    created = 0
    for k, v in raw.items():
        try:
            rec_id = int(k)
        except Exception:
            continue

        if isinstance(v, str):
            message_id = v
            status = "active"
        elif isinstance(v, dict):
            message_id = v.get("message_id")
            status = "finalized" if bool(v.get("finalized", False)) else "active"
        else:
            continue

        if not isinstance(message_id, str) or not message_id.strip():
            continue

        exists = (
            db.query(MarketTrackingMessage)
            .filter(MarketTrackingMessage.recommendation_id == rec_id)
            .first()
        )
        if exists:
            continue

        db.add(
            MarketTrackingMessage(
                recommendation_id=rec_id,
                discord_message_id=message_id.strip(),
                status=status,
            )
        )
        created += 1

    if created:
        _db_commit_with_retry(db)
        logger.info("bootstrapped %s market tracking messages from old cache", created)


def _db_commit_with_retry(db, *, attempts: int = 5) -> None:
    """Commit with retries for SQLite lock contention.

    Multiple processes write to the same SQLite file (automation, tracker, etc.).
    WAL + busy_timeout help, but we still retry to avoid dropping updates.
    """

    delay_s = 0.2
    for i in range(attempts):
        try:
            db.commit()
            return
        except OperationalError as e:
            msg = str(e).lower()
            if "locked" in msg or "busy" in msg:
                time.sleep(delay_s)
                delay_s = min(2.0, delay_s * 2)
                continue
            raise

    # Last attempt: raise the last error
    db.commit()


def _format_last_update_ct(last_update: str | None) -> str:
    """Format ISO timestamp string into US Central time (CT)."""
    if not last_update:
        return ""

    try:
        # Handles '2026-03-02T02:40:03.123+00:00'
        dt = datetime.fromisoformat(str(last_update).replace('Z', '+00:00'))
        dt_ct = dt.astimezone(ZoneInfo('America/Chicago'))
        return dt_ct.strftime('%H:%M:%S')
    except Exception:
        return ""

def _updated_label(snap) -> str:
    ts = _format_last_update_ct(getattr(snap, "last_update", None))
    if not ts:
        return ""
    return f"Updated: {ts} CT"



def _snapshot_age_seconds(snap, now_utc: datetime) -> float | None:
    last = getattr(snap, "last_update", None)
    if not last:
        return None
    try:
        dt = datetime.fromisoformat(str(last).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (now_utc - dt).total_seconds()
    except Exception:
        return None


def _snapshot_is_stale(snap, now_utc: datetime) -> bool:
    age = _snapshot_age_seconds(snap, now_utc)
    if age is None:
        return False
    return age > STALE_ODDS_SECONDS



def _parse_team_from_pick(pick: str) -> Optional[str]:
    if not pick:
        return None
    # Spread pick formats: "BKN +4.5" or "ORL -2.5"
    # Total pick formats: "OVER 248.5" (no team)
    return pick.strip().split()[0].upper()


def _is_total_pick(pick: str) -> bool:
    if not pick:
        return False
    return pick.strip().upper().startswith("OVER") or pick.strip().upper().startswith("UNDER")


def _total_side(pick: str) -> str:
    return pick.strip().split()[0].upper()


def _team_total_team(pick: str) -> Optional[str]:
    if not pick:
        return None
    parts = pick.strip().split()
    return parts[0].upper() if parts else None


def _team_total_side(pick: str) -> Optional[str]:
    if not pick:
        return None
    parts = pick.strip().split()
    if len(parts) < 2:
        return None
    side = parts[1].upper()
    return side if side in ("OVER", "UNDER") else None


def _moneyline_team(pick: str) -> Optional[str]:
    if not pick:
        return None
    parts = pick.strip().split()
    return parts[0].upper() if parts else None


def _ticket_label_for_rec(game: Game, rec: BettingRecommendation) -> str:
    bt = str(getattr(rec.bet_type, "value", rec.bet_type)).upper()
    if bt == "SPREAD":
        team = _parse_team_from_pick(rec.pick) or "?"
        return f"{team} {float(rec.line):+0.1f}"
    if bt == "TOTAL":
        side = _total_side(rec.pick)
        return f"{side} {float(rec.line):.1f}"
    if bt == "TEAM_TOTAL":
        team = _team_total_team(rec.pick) or "?"
        side = _team_total_side(rec.pick) or "?"
        return f"{team} {side} {float(rec.line):.1f}"
    if bt == "MONEYLINE":
        team = _moneyline_team(rec.pick) or "?"
        return f"{team} ML"
    return rec.pick


def _live_label_from_snapshot(game: Game, rec: BettingRecommendation, snap) -> str:
    bt = str(getattr(rec.bet_type, "value", rec.bet_type)).upper()
    if bt == "SPREAD":
        if snap.spread_home is None:
            return "Spread market unavailable"

        home_line = float(snap.spread_home)
        team = _parse_team_from_pick(rec.pick)

        if team and team.upper() == game.home_team.upper():
            return f"{game.home_team} {home_line:+.1f}"
        if team and team.upper() == game.away_team.upper():
            return f"{game.away_team} {-home_line:+.1f}"

        # Fallback
        return f"{game.home_team} {home_line:+.1f}"
    if bt == "TOTAL":
        if snap.total_points is None:
            return "Total market unavailable"
        return f"O/U {float(snap.total_points):.1f}"
    if bt == "TEAM_TOTAL":
        team = _team_total_team(rec.pick)
        if not team:
            return "Team total market unavailable"

        if team.upper() == game.home_team.upper():
            live = snap.team_total_home if snap.team_total_home is not None else snap.derived_team_total_home
        elif team.upper() == game.away_team.upper():
            live = snap.team_total_away if snap.team_total_away is not None else snap.derived_team_total_away
        else:
            live = None

        if live is None:
            return "Team total market unavailable"
        return f"{team} TT {float(live):.1f}"

    if bt == "MONEYLINE":
        team = _moneyline_team(rec.pick)
        if not team:
            return "Moneyline market unavailable"

        if team.upper() == game.home_team.upper():
            odds = snap.moneyline_home
        elif team.upper() == game.away_team.upper():
            odds = snap.moneyline_away
        else:
            odds = None

        if odds is None:
            return "Moneyline market unavailable"
        return f"{team} ML {int(odds):+d}"
    return ""


def _move_vs_ticket_pts(game: Game, rec: BettingRecommendation, snap) -> Optional[float]:
    bt = str(getattr(rec.bet_type, "value", rec.bet_type)).upper()
    if bt == "TEAM_TOTAL" and rec.line is not None:
        team = _team_total_team(rec.pick)
        if not team:
            return None

        if team.upper() == game.home_team.upper():
            live = snap.team_total_home if snap.team_total_home is not None else snap.derived_team_total_home
        elif team.upper() == game.away_team.upper():
            live = snap.team_total_away if snap.team_total_away is not None else snap.derived_team_total_away
        else:
            live = None

        if live is None:
            return None
        return float(live) - float(rec.line)

    if bt == "MONEYLINE" and rec.odds is not None:
        # Move is odds delta vs ticket odds (market - ticket)
        team = _moneyline_team(rec.pick)
        if not team:
            return None
        if team.upper() == game.home_team.upper():
            live_odds = snap.moneyline_home
        elif team.upper() == game.away_team.upper():
            live_odds = snap.moneyline_away
        else:
            live_odds = None
        if live_odds is None:
            return None
        return float(live_odds) - float(rec.odds)

    if bt == "SPREAD" and snap.spread_home is not None and rec.line is not None:
        team = _parse_team_from_pick(rec.pick)
        if not team:
            return None
        if team.upper() == game.home_team.upper():
            # more positive = moved against a negative favorite line
            return float(snap.spread_home) - float(rec.line)
        if team.upper() == game.away_team.upper():
            # away ticket line is stored signed for away team; current away line is -spread_home
            return float(-snap.spread_home) - float(rec.line)
    if bt == "TOTAL" and snap.total_points is not None and rec.line is not None:
        return float(snap.total_points) - float(rec.line)
    return None

def _move_detail(game: Game, rec: BettingRecommendation, snap) -> Optional[str]:
    """Human-friendly move label showing ticket -> live line."""
    bt = str(getattr(rec.bet_type, "value", rec.bet_type)).upper()

    if bt == "TEAM_TOTAL" and rec.line is not None:
        team = _team_total_team(rec.pick)
        side = _team_total_side(rec.pick)
        if not team or not side:
            return None

        if team.upper() == game.home_team.upper():
            live = snap.team_total_home if snap.team_total_home is not None else snap.derived_team_total_home
        elif team.upper() == game.away_team.upper():
            live = snap.team_total_away if snap.team_total_away is not None else snap.derived_team_total_away
        else:
            live = None

        if live is None:
            return None

        delta = float(live) - float(rec.line)
        favorable = (side == "UNDER" and delta < 0) or (side == "OVER" and delta > 0)
        tag = "✅ Favorable" if favorable else "❌ Unfavorable"
        return f"Move {delta:+.1f} -- {tag}"

    if bt == "MONEYLINE":
        # Favorability: if we have ticket odds, compare implied win prob at live odds vs ticket odds
        team = _moneyline_team(rec.pick)
        if not team:
            return "Move N/A"

        if team.upper() == game.home_team.upper():
            live_odds = snap.moneyline_home
        elif team.upper() == game.away_team.upper():
            live_odds = snap.moneyline_away
        else:
            live_odds = None

        if live_odds is None:
            return "Move N/A"

        def imp(o: int) -> float:
            if o < 0:
                return (-o) / ((-o) + 100.0)
            return 100.0 / (o + 100.0)

        if rec.odds is None:
            return "Move N/A"

        # Higher win prob now than at ticket odds is favorable
        favorable = imp(int(live_odds)) > imp(int(rec.odds))
        tag = "✅ Favorable" if favorable else "❌ Unfavorable"
        return f"Move {float(live_odds) - float(rec.odds):+.0f} -- {tag}"


    if bt == "TOTAL" and snap.total_points is not None and rec.line is not None:
        live = float(snap.total_points)
        ticket = float(rec.line)
        delta = live - ticket
        side = (rec.pick or "").strip().upper()
        favorable = (side.startswith("UNDER") and delta < 0) or (side.startswith("OVER") and delta > 0)
        tag = "✅ Favorable" if favorable else "❌ Unfavorable"
        return f"Move {delta:+.1f} -- {tag}"

    if bt == "SPREAD" and snap.spread_home is not None and rec.line is not None:
        team = _parse_team_from_pick(rec.pick)
        if not team:
            return None
        ticket = float(rec.line)
        if team.upper() == game.home_team.upper():
            live = float(snap.spread_home)
        elif team.upper() == game.away_team.upper():
            live = float(-snap.spread_home)
        else:
            return None
        delta = live - ticket
        # For spreads: moving toward zero is favorable for dogs; away/toward more negative is favorable for favs
        team = _parse_team_from_pick(rec.pick) or ""
        # Determine if ticket is favorite (negative line) or underdog (positive line)
        favorite = ticket < 0
        favorable = (favorite and delta < 0) or ((not favorite) and delta > 0)
        tag = "✅ Favorable" if favorable else "❌ Unfavorable"
        return f"Move {delta:+.1f} -- {tag}"

    return None




def _resolve_moneyline_result(
    *,
    final_home: float,
    final_away: float,
    pick_team: str,
    home_team: str,
    away_team: str,
) -> str:
    pick = (pick_team or '').upper().strip()
    if final_home == final_away:
        return 'push'
    winner = home_team.upper() if final_home > final_away else away_team.upper()
    return 'won' if pick == winner else 'lost'


def _resolve_team_total_result(*, team_score: float, line: float, pick: str) -> str:
    # Use the total resolver semantics (OVER/UNDER on one team's score)
    return resolve_total_bet(team_score, float(line), pick)

def _humanize_notes(notes: Tuple[str, ...], game: Game, rec: BettingRecommendation) -> Tuple[str, ...]:
    """Turn terse debug notes into plain language for the Discord embed."""

    out = []
    bt = str(getattr(rec.bet_type, "value", rec.bet_type)).upper()

    for n in notes:
        s = str(n or "").strip()

        if bt == "TOTAL" and s.startswith("fair_p_over="):
            # Internal debug signal; not shown in the Discord embed
            continue

        if bt == "SPREAD" and s.startswith("fair_p_home_cover="):
            # Internal debug signal; not shown in the Discord embed
            continue

        # Default: keep as-is, but make it readable-ish
        if s:
            out.append(s.replace("_", " "))

    return tuple(out)



def _compute_p_hit(game: Game, rec: BettingRecommendation, snap, sigma: SigmaConfig) -> Tuple[Optional[float], Tuple[str, ...]]:
    bt = str(getattr(rec.bet_type, "value", rec.bet_type)).upper()

    if bt == "SPREAD":
        team = _parse_team_from_pick(rec.pick)
        if not team:
            return None, ("could not parse team from pick",)
        if snap.spread_home is None or snap.spread_home_odds is None or snap.spread_away_odds is None:
            return None, ("spread market missing",)
        res = estimate_spread_from_snapshot(
            home_team=game.home_team,
            away_team=game.away_team,
            ticket_team=team,
            ticket_line=float(rec.line),
            spread_home=float(snap.spread_home),
            spread_home_odds=int(snap.spread_home_odds),
            spread_away_odds=int(snap.spread_away_odds),
            sigma_cfg=sigma,
        )
        return res.p_hit, res.notes

    if bt == "TEAM_TOTAL":
        team = _team_total_team(rec.pick)
        side = _team_total_side(rec.pick)
        if not team or not side:
            return None, ("could not parse team total",)

        if team.upper() == game.home_team.upper():
            pts = snap.team_total_home if snap.team_total_home is not None else snap.derived_team_total_home
            o_odds = snap.team_total_home_over_odds
            u_odds = snap.team_total_home_under_odds
        elif team.upper() == game.away_team.upper():
            pts = snap.team_total_away if snap.team_total_away is not None else snap.derived_team_total_away
            o_odds = snap.team_total_away_over_odds
            u_odds = snap.team_total_away_under_odds
        else:
            return None, ("team total team mismatch",)

        if pts is None:
            return None, ("team total market missing",)

        # If we don't have explicit team-total odds, assume -110/-110
        over_odds = int(o_odds) if o_odds is not None else -110
        under_odds = int(u_odds) if u_odds is not None else -110

        res = estimate_total_from_snapshot(
            ticket_side=side,
            ticket_line=float(rec.line),
            total_points=float(pts),
            total_over_odds=over_odds,
            total_under_odds=under_odds,
            sigma_cfg=sigma,
        )
        return res.p_hit, res.notes

    if bt == "MONEYLINE":
        team = _moneyline_team(rec.pick)
        if not team:
            return None, ("could not parse moneyline team",)
        if snap.moneyline_home is None or snap.moneyline_away is None:
            return None, ("moneyline market missing",)

        def imp(o: int) -> float:
            if o < 0:
                return (-o) / ((-o) + 100.0)
            return 100.0 / (o + 100.0)

        p_home = imp(int(snap.moneyline_home))
        p_away = imp(int(snap.moneyline_away))
        z = p_home + p_away
        if z <= 0:
            return None, ("moneyline invalid",)
        fair_home = p_home / z
        fair_away = p_away / z

        if team.upper() == game.home_team.upper():
            return float(fair_home), ()
        if team.upper() == game.away_team.upper():
            return float(fair_away), ()
        return None, ("moneyline team mismatch",)

    if bt == "TOTAL":
        if not _is_total_pick(rec.pick):
            return None, ("could not parse total side",)
        if snap.total_points is None or snap.total_over_odds is None or snap.total_under_odds is None:
            return None, ("total market missing",)
        res = estimate_total_from_snapshot(
            ticket_side=_total_side(rec.pick),
            ticket_line=float(rec.line),
            total_points=float(snap.total_points),
            total_over_odds=int(snap.total_over_odds),
            total_under_odds=int(snap.total_under_odds),
            sigma_cfg=sigma,
        )
        return res.p_hit, res.notes

    return None, ("unsupported bet type",)


def main() -> None:
    load_dotenv(Path(__file__).resolve().parent / ".env")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    cfg = RunnerConfig(
        poll_seconds=int(os.environ.get("MARKET_TRACK_POLL_SECONDS", "30")),
        edit_seconds=int(os.environ.get("MARKET_TRACK_EDIT_SECONDS", "60")),
        lookback_hours=int(os.environ.get("MARKET_TRACK_LOOKBACK_HOURS", "6")),
        min_rec_prob=float(os.environ.get("MARKET_TRACK_MIN_REC_PROB", "0.72")),
    )

    discord_cfg = DiscordAdapterConfig.from_env()
    if not discord_cfg.webhook_url:
        raise SystemExit("Missing DISCORD_LIVE_TRACKING_WEBHOOK (or DISCORD_WEBHOOK_URL fallback)")

    publisher = MarketDiscordPublisher(discord_cfg)

    policy = TierPolicy()
    tracker = StateTracker(policy=policy)
    sigma = SigmaConfig()

    bootstrapped = False

    logger.info("market tracking sidecar started")
    try:
        HEARTBEAT_PATH.write_text(datetime.now(timezone.utc).isoformat())
    except Exception:
        pass
    logger.info("poll_seconds=%s edit_seconds=%s", cfg.poll_seconds, cfg.edit_seconds)

    while True:
        start = time.time()
        now = datetime.now(timezone.utc)
        new_posts_this_cycle = 0
        try:
            HEARTBEAT_PATH.write_text(now.isoformat())
        except Exception:
            pass
        db = SessionLocal()
        try:
            if not bootstrapped:
                _bootstrap_tracking_messages_from_cache(db)
                bootstrapped = True
            cutoff = now - timedelta(hours=cfg.lookback_hours)

            preds = (
                db.query(Prediction, Game)
                .join(Game)
                .filter(
                    Prediction.trigger_type == TriggerType.HALFTIME,
                    Prediction.posted_to_discord == True,  # noqa: E712
                    Prediction.created_at >= cutoff.replace(tzinfo=None),
                )
                .order_by(Prediction.created_at.desc())
                .limit(25)
                .all()
            )

            for pred, game in preds:
                # Track only games that have started. If Final, do one last finalize edit.
                status = (game.game_status or "").strip().lower()
                if status == "scheduled":
                    continue
                if (game.period or 0) <= 0 and status != "final":
                    continue
                recs = (
                    db.query(BettingRecommendation)
                    .filter(BettingRecommendation.prediction_id == pred.id)
                    .all()
                )

                for rec in recs:
                    # Only track high-confidence recommendations (filter only; tracking math remains market-only).
                    try:
                        rec_prob = float(rec.probability) if rec.probability is not None else 0.0
                    except Exception:
                        rec_prob = 0.0
                    if rec_prob < cfg.min_rec_prob:
                        continue
                    bt = str(getattr(rec.bet_type, "value", rec.bet_type)).upper()
                    if bt not in ("SPREAD", "TOTAL", "TEAM_TOTAL", "MONEYLINE"):
                        continue

                    rec_key = str(rec.id)

                    # If game ended, finalize tracker message once (verdict + stop).
                    if status == "final":
                        entry = db.query(MarketTrackingMessage).filter(MarketTrackingMessage.recommendation_id == rec.id).first()

                        # Catch-up: if we never created a tracker for this rec, post a final-only message now.
                        if not entry:
                            final_home = float(game.final_home_score or 0)
                            final_away = float(game.final_away_score or 0)
                            matchup = f"{game.away_team} @ {game.home_team}"
                            final_score = f"{int(final_away)} - {int(final_home)}"
                            ticket_label = _ticket_label_for_rec(game, rec)

                            bt2 = str(getattr(rec.bet_type, "value", rec.bet_type)).upper()
                            if bt2 == "SPREAD":
                                result = resolve_spread_bet(
                                    final_home,
                                    final_away,
                                    float(rec.line or 0.0),
                                    rec.pick or "",
                                    game.home_team,
                                    game.away_team,
                                )
                            elif bt2 == "TOTAL":
                                result = resolve_total_bet(final_home + final_away, float(rec.line or 0.0), rec.pick or "")
                            elif bt2 == "TEAM_TOTAL":
                                team = _team_total_team(rec.pick) or ""
                                side = _team_total_side(rec.pick) or rec.pick or ""
                                if team.upper() == game.home_team.upper():
                                    team_score = final_home
                                else:
                                    team_score = final_away
                                result = _resolve_team_total_result(team_score=team_score, line=float(rec.line or 0.0), pick=side)
                            else:  # MONEYLINE
                                team = _moneyline_team(rec.pick) or ""
                                result = _resolve_moneyline_result(
                                    final_home=final_home,
                                    final_away=final_away,
                                    pick_team=team,
                                    home_team=game.home_team,
                                    away_team=game.away_team,
                                )

                            embed_final = build_final_embed(
                                matchup=matchup,
                                ticket_label=ticket_label,
                                final_score=final_score,
                                result=result,
                            )
                            if new_posts_this_cycle >= MAX_NEW_POSTS_PER_CYCLE:
                                continue
                            mid = publisher.post_tracker(content="", embed=embed_final)
                            if mid:
                                new_posts_this_cycle += 1
                                entry = MarketTrackingMessage(
                                    recommendation_id=rec.id,
                                    discord_message_id=str(mid),
                                    status="finalized",
                                )
                                db.add(entry)
                                _db_commit_with_retry(db)
                            continue
                        if (entry.status or "").lower() == "finalized":
                            continue

                        final_home = float(game.final_home_score or 0)
                        final_away = float(game.final_away_score or 0)
                        matchup = f"{game.away_team} @ {game.home_team}"
                        final_score = f"{int(final_away)} - {int(final_home)}"
                        ticket_label = _ticket_label_for_rec(game, rec)
                        bt2 = str(getattr(rec.bet_type, "value", rec.bet_type)).upper()
                        if bt2 == "SPREAD":
                            result = resolve_spread_bet(final_home, final_away, float(rec.line or 0.0), rec.pick or "", game.home_team, game.away_team)
                        elif bt2 == "TOTAL":
                            result = resolve_total_bet(final_home + final_away, float(rec.line or 0.0), rec.pick or "")
                        elif bt2 == "TEAM_TOTAL":
                            team = _team_total_team(rec.pick) or ""
                            side = _team_total_side(rec.pick) or rec.pick or ""
                            if team.upper() == game.home_team.upper():
                                team_score = final_home
                            else:
                                team_score = final_away
                            result = _resolve_team_total_result(team_score=team_score, line=float(rec.line or 0.0), pick=side)
                        else:  # MONEYLINE
                            team = _moneyline_team(rec.pick) or ""
                            result = _resolve_moneyline_result(
                                final_home=final_home,
                                final_away=final_away,
                                pick_team=team,
                                home_team=game.home_team,
                                away_team=game.away_team,
                            )

                        # Write back official outcome into DB for dashboard consistency
                        res_norm = (result or "").lower().strip()
                        if res_norm == "won":
                            rec.result = BetStatus.WON
                        elif res_norm == "push":
                            rec.result = BetStatus.PUSH
                        else:
                            rec.result = BetStatus.LOST
                        db.add(rec)
                        _db_commit_with_retry(db)

                        embed_final = build_final_embed(
                            matchup=matchup,
                            ticket_label=ticket_label,
                            final_score=final_score,
                            result=result,
                        )
                        publisher.edit_tracker(message_id=str(entry.discord_message_id), content="", embed=embed_final)
                        entry.status = "finalized"
                        db.add(entry)
                        _db_commit_with_retry(db)
                        continue

                    # Create or update a tracker message (DB-backed idempotency)
                    entry = (
                        db.query(MarketTrackingMessage)
                        .filter(MarketTrackingMessage.recommendation_id == rec.id)
                        .first()
                    )

                    # If entry is already done, don't spend cycles on odds.
                    if entry and (entry.status or '').lower() in ('finalized', 'failed'):
                        continue

                    now_naive = now.replace(tzinfo=None)

                    need_post = entry is None
                    last = entry.last_edited_at if entry else None
                    need_edit = need_post or last is None or (now_naive - last).total_seconds() >= cfg.edit_seconds
                    if not need_edit:
                        continue

                    # Fetch market snapshot (local-only)
                    try:
                        snap = fetch_local_snapshot(
                            LocalOddsQuery(home=game.home_team, away=game.away_team, timeout_s=10)
                        )
                    except Exception as e:
                        logger.info(
                            "local odds unavailable for %s@%s: %s",
                            game.away_team,
                            game.home_team,
                            e,
                        )
                        continue

                    # Stale odds guard: don't update Discord with old data.
                    if not need_post and _snapshot_is_stale(snap, now):
                        continue

                    p_hit, notes = _compute_p_hit(game, rec, snap, sigma)
                    if p_hit is None:
                        continue

                    display_notes = _humanize_notes(notes, game, rec)
                    move_pts = _move_vs_ticket_pts(game, rec, snap)

                    # Trend (restart-safe) only on edit/post ticks
                    target = now_naive - timedelta(seconds=120)
                    prev_pt = (
                        db.query(MarketTrackingPoint)
                        .filter(
                            MarketTrackingPoint.recommendation_id == rec.id,
                            MarketTrackingPoint.timestamp_utc <= target,
                        )
                        .order_by(MarketTrackingPoint.timestamp_utc.desc())
                        .first()
                    )
                    delta_2m = (float(p_hit) - float(prev_pt.p_hit)) if prev_pt is not None else None

                    # State tiering (still in-memory, but cheap)
                    est = ProbabilityEstimate(
                        bet_id=str(rec.id),
                        timestamp_utc=now,
                        p_hit=float(p_hit),
                        move_points_against_ticket=move_pts,
                        notes=notes,
                    )
                    st = tracker.upsert(est)
                    tier = st.current_tier or tier_for_p(est.p_hit, policy)

                    ticket_label = _ticket_label_for_rec(game, rec)
                    live_label = _live_label_from_snapshot(game, rec, snap)
                    matchup = f"{game.away_team} @ {game.home_team}"

                    embed = build_tracking_embed(
                        matchup=matchup,
                        ticket_label=ticket_label,
                        live_label=live_label,
                        p_hit=float(p_hit),
                        tier=tier,
                        delta_2m=delta_2m,
                        move_pts=move_pts,
                        move_detail=_move_detail(game, rec, snap),
                        updated_label=_updated_label(snap),
                        notes=display_notes,
                    )

                    MAX_EDIT_FAILURES = int(os.environ.get('MARKET_TRACK_MAX_EDIT_FAILURES', '5'))

                    if need_post:
                        if new_posts_this_cycle >= MAX_NEW_POSTS_PER_CYCLE:
                            continue
                        mid = publisher.post_tracker(content="", embed=embed)
                        if not mid:
                            continue
                        new_posts_this_cycle += 1
                        entry = MarketTrackingMessage(
                            recommendation_id=rec.id,
                            discord_message_id=str(mid),
                            status='active',
                            last_edited_at=now_naive,
                            consecutive_edit_failures=0,
                            last_error=None,
                        )
                        db.add(entry)
                        db.add(
                            MarketTrackingPoint(
                                recommendation_id=rec.id,
                                timestamp_utc=now_naive,
                                p_hit=float(p_hit),
                            )
                        )
                        _db_commit_with_retry(db)
                        continue

                    # Edit existing tracker
                    ok = publisher.edit_tracker(message_id=str(entry.discord_message_id), content="", embed=embed)
                    if ok:
                        # One commit for all DB writes
                        entry.last_edited_at = now_naive
                        entry.consecutive_edit_failures = 0
                        entry.last_error = None
                        db.add(entry)

                        db.add(
                            MarketTrackingPoint(
                                recommendation_id=rec.id,
                                timestamp_utc=now_naive,
                                p_hit=float(p_hit),
                            )
                        )

                        prune_before = now_naive - timedelta(hours=4)
                        (
                            db.query(MarketTrackingPoint)
                            .filter(
                                MarketTrackingPoint.recommendation_id == rec.id,
                                MarketTrackingPoint.timestamp_utc < prune_before,
                            )
                            .delete(synchronize_session=False)
                        )

                        _db_commit_with_retry(db)
                    else:
                        entry.consecutive_edit_failures = int(entry.consecutive_edit_failures or 0) + 1
                        entry.last_error = 'discord edit failed'
                        if entry.consecutive_edit_failures >= MAX_EDIT_FAILURES:
                            entry.status = 'failed'
                        db.add(entry)
                        _db_commit_with_retry(db)
        finally:
            db.close()

        elapsed = time.time() - start
        sleep_for = max(1.0, cfg.poll_seconds - elapsed)
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()

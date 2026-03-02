"""MAXIMUS Yesterday Pregame Backtest (Capabilities Demo)

Runs pregame projections for yesterday using ONLY information available pre-tip:
- Features pulled from TemporalFeatureStore as-of tip time
- MAXIMUS pregame model inference

Then fetches actual final scores from NBA CDN boxscore and reports:
- Winner accuracy
- Total MAE
- Margin MAE

Optionally posts results to Discord (MAXIMUS pregame channel).

This is intentionally a *manual* script (not part of daemon loop).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from src.automation.discord_client import DiscordClient
from src.data.game_data import fetch_box
from src.data.pregame_features import PregameFeatureContext, build_pregame_features
from src.models.pregame import get_pregame_model
from src.schedule import fetch_schedule
from src.utils.datetime_utils import as_utc
from src.utils.league_time import league_day_str, league_now, format_league_dt


@dataclass(frozen=True)
class GameResult:
    away: str
    home: str
    tip_local: str
    pred_total: float
    pred_margin: float
    pred_winner: str
    pred_win_prob: float
    actual_away: int
    actual_home: int

    @property
    def actual_total(self) -> int:
        return int(self.actual_away + self.actual_home)

    @property
    def actual_margin(self) -> int:
        # home - away
        return int(self.actual_home - self.actual_away)

    @property
    def total_error(self) -> float:
        return abs(self.pred_total - float(self.actual_total))

    @property
    def margin_error(self) -> float:
        return abs(self.pred_margin - float(self.actual_margin))

    @property
    def winner_correct(self) -> bool:
        actual_winner = self.home if self.actual_margin > 0 else self.away
        return actual_winner == self.pred_winner


def _load_env(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _parse_game_dt(game: dict) -> Optional[datetime]:
    dt_str = game.get("date_time")
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception:
        return None


def run_yesterday_backtest(*, post_to_discord: bool = True, limit: Optional[int] = None) -> str:
    model = get_pregame_model()
    if model is None or not model._loaded:
        raise RuntimeError("MAXIMUS pregame model not loaded")

    # Yesterday in league time
    yday_local = league_now() - timedelta(days=1)
    yday_str = league_day_str(yday_local)

    sched = fetch_schedule(yday_str)
    games = [g for g in sched.get("games", []) if g.get("nba_id")]
    if limit:
        games = games[:limit]

    results: List[GameResult] = []

    for g in games:
        gid = str(g.get("nba_id"))
        home = str((g.get("home_team") or "").upper())
        away = str((g.get("away_team") or "").upper())
        if not home or not away:
            continue

        game_dt = _parse_game_dt(g)
        if game_dt is None:
            continue
        game_dt_utc = as_utc(game_dt)
        tip_local = format_league_dt(game_dt_utc, fmt="%I:%M %p %Z")

        feats = build_pregame_features(
            PregameFeatureContext(
                game_id=gid,
                home_tricode=home,
                away_tricode=away,
                game_datetime=game_dt_utc,
            )
        )
        pred = model.predict(feats, game_id=gid)
        if pred is None:
            continue

        pred_total = float(pred.total_mean)
        pred_margin = float(pred.margin_mean)  # home - away
        pred_home_score = (pred_total + pred_margin) / 2.0
        pred_away_score = (pred_total - pred_margin) / 2.0

        pred_winner = home if pred_margin > 0 else away
        pred_win_prob = float(pred.home_win_prob if pred_margin > 0 else (1.0 - pred.home_win_prob))

        box = fetch_box(gid)
        actual_home = int(box.get("homeTeam", {}).get("score") or 0)
        actual_away = int(box.get("awayTeam", {}).get("score") or 0)

        results.append(
            GameResult(
                away=away,
                home=home,
                tip_local=tip_local,
                pred_total=pred_total,
                pred_margin=pred_margin,
                pred_winner=pred_winner,
                pred_win_prob=pred_win_prob,
                actual_away=actual_away,
                actual_home=actual_home,
            )
        )

    if not results:
        return f"No games found for {yday_str}"

    # Metrics
    winner_acc = sum(1 for r in results if r.winner_correct) / len(results)
    total_mae = sum(r.total_error for r in results) / len(results)
    margin_mae = sum(r.margin_error for r in results) / len(results)

    lines: List[str] = [
        "🧪 **MAXIMUS BACKTEST — YESTERDAY (PREGAME)**",
        f"Date: **{yday_str}**",
        "",
        f"Games: **{len(results)}**",
        f"Winner Accuracy: **{winner_acc:.0%}**",
        f"Total MAE: **{total_mae:.1f}**",
        f"Margin MAE: **{margin_mae:.1f}**",
        "",
        "---",
        "",
        "**Per-Game**",
    ]

    for r in results:
        pred_home = (r.pred_total + r.pred_margin) / 2.0
        pred_away = (r.pred_total - r.pred_margin) / 2.0
        lines.append(f"**{r.away} @ {r.home}** — {r.tip_local}")
        lines.append(
            f"Pred: {r.away} {pred_away:.0f} - {r.home} {pred_home:.0f} | T {r.pred_total:.1f} | M {r.pred_margin:+.1f} | {r.pred_winner} {r.pred_win_prob:.0%}"
        )
        lines.append(
            f"Actual: {r.away} {r.actual_away} - {r.home} {r.actual_home} | T {r.actual_total} | M {r.actual_margin:+d} | {'✅' if r.winner_correct else '❌'}"
        )
        lines.append("")

    content = "\n".join(lines)[:1990]

    if post_to_discord:
        _load_env()
        webhook = os.environ.get("DISCORD_MAXIMUS_PREGAME_WEBHOOK", "").strip()
        if not webhook:
            raise RuntimeError("Missing DISCORD_MAXIMUS_PREGAME_WEBHOOK")
        DiscordClient(webhook, username="MAXIMUS (BACKTEST)").post_message(content)

    return content


if __name__ == "__main__":
    print(run_yesterday_backtest(post_to_discord=False))

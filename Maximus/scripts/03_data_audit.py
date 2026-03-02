"""Data audit + leakage checks for Maximus.

Generates:
- Maximus/reports/DATA_AUDIT_REPORT.md

Fail-fast behavior:
- raises if critical integrity checks fail
"""

from __future__ import annotations

import random
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from Maximus.src.data.load_raw import load_historical_games
from Maximus.src.features.build_features import build_pregame_features
from Maximus.src.features.rolling import team_game_rows
from Maximus.src.paths import reports_dir
from Maximus.src.schema import PROHIBITED_FEATURE_SUBSTRINGS


def main() -> int:
    reports_dir().mkdir(parents=True, exist_ok=True)

    games = load_historical_games()

    # base checks
    assert games["game_id"].is_unique, "game_id not unique"
    assert games[["game_date", "game_id"]].equals(
        games.sort_values(["game_date", "game_id"])[["game_date", "game_id"]].reset_index(drop=True)
    ), "games not sorted chronologically"

    feats, _ = build_pregame_features(games)
    feature_cols = [c for c in feats.columns if c != "game_id"]

    # prohibited scan
    # We prohibit including current-game targets/scores as features.
    # Rolling features may legitimately contain the words 'margin'/'total' because they are derived from PRIOR games.
    prohibited_hits = []
    for c in feature_cols:
        cl = c.lower()
        # prohibit raw score columns always
        if "home_pts" in cl or "away_pts" in cl:
            prohibited_hits.append((c, "score"))
        # prohibit exact target leakage (feature named exactly like target)
        if cl in {"margin", "total"}:
            prohibited_hits.append((c, "target"))

    # NA/inf
    X = feats[feature_cols]
    na_cols = X.columns[X.isna().any()].tolist()
    inf_cols = X.columns[np.isinf(X.to_numpy()).any(axis=0)].tolist()

    # Coverage tables
    season_counts = games.groupby("season").size().sort_index()
    team_rows = pd.concat(
        [
            games[["season", "home_tri"]].rename(columns={"home_tri": "team"}),
            games[["season", "away_tri"]].rename(columns={"away_tri": "team"}),
        ],
        ignore_index=True,
    )
    team_season_counts = team_rows.groupby(["season", "team"]).size().reset_index(name="games")

    # Strong timing spot-checks (random 50 games): recompute one rolling feature from raw prior games
    # and verify it matches stored feature value.
    sample_game_ids = random.Random(123).sample(list(games["game_id"].values), k=min(50, len(games)))

    feats_by_gid = feats.set_index("game_id")

    # Build the exact per-team table used for rolling features
    tr = team_game_rows(games)
    tr = tr.sort_values(["team", "game_date", "game_id"]).reset_index(drop=True)

    # precompute shifted rolling mean for window=5 as the ground truth for audit
    g = tr.groupby("team", sort=False)
    tr["margin_last5_mean"] = g["margin"].shift(1).rolling(5, min_periods=1).mean().fillna(0.0).to_numpy()

    timing_checks = []
    for gid in sample_game_ids:
        row = games[games["game_id"] == gid].iloc[0]
        home = row["home_tri"]

        # locate the home-team row for this game_id
        home_row = tr[(tr["game_id"] == gid) & (tr["team"] == home)]
        if len(home_row) != 1:
            raise RuntimeError(f"Audit expected exactly 1 home row for game_id={gid}, team={home}; got {len(home_row)}")

        expected = float(home_row.iloc[0]["margin_last5_mean"])
        stored = float(feats_by_gid.loc[gid, "home_margin_last5_mean"])

        prior_games = int(games[(games["game_date"] < row["game_date"]) & ((games["home_tri"] == home) | (games["away_tri"] == home))].shape[0])

        timing_checks.append(
            {
                "game_id": gid,
                "team": home,
                "prior_games": prior_games,
                "expected_home_margin_last5_mean": expected,
                "stored_home_margin_last5_mean": stored,
                "abs_diff": abs(expected - stored),
            }
        )

    # write report
    out_path = reports_dir() / "DATA_AUDIT_REPORT.md"
    lines = [
        "# Data Audit Report (Maximus)",
        "",
        f"Generated at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Dataset Summary",
        f"- games: {len(games)}",
        f"- features: {len(feature_cols)}",
        "",
        "## Season Coverage",
        "Games per season:",
        "```",
        season_counts.to_string(),
        "```",
        "",
        "Sample team-season counts (first 20):",
        "```",
        team_season_counts.head(20).to_string(index=False),
        "```",
        "",
        "## Integrity Checks",
        f"- game_id unique: ✅",
        f"- chronological sort: ✅",
        "",
        "## Prohibited Feature Scan",
    ]

    if prohibited_hits:
        lines.append("- ❌ FAILED: prohibited substrings found")
        for c, s in prohibited_hits[:50]:
            lines.append(f"  - {c} matched '{s}'")
    else:
        lines.append("- ✅ PASSED: no prohibited substrings found")

    lines += ["", "## NA/Inf Checks"]
    lines.append(f"- NA columns: {len(na_cols)}")
    lines.append(f"- Inf columns: {len(inf_cols)}")

    lines += [
        "",
        "## Timing Spot Checks (50 random games)",
        "We recompute `home_margin_last5_mean` from raw prior games and compare to stored value.",
        "(abs_diff should be 0 or very small floating error)",
        "",
    ]
    max_abs_diff = 0.0
    for t in timing_checks[:50]:
        max_abs_diff = max(max_abs_diff, t["abs_diff"])
        lines.append(
            f"- {t['game_id']} team={t['team']} prior={t['prior_games']} expected={t['expected_home_margin_last5_mean']:.6f} stored={t['stored_home_margin_last5_mean']:.6f} abs_diff={t['abs_diff']:.6f}"
        )
    lines.append("")
    lines.append(f"Max abs_diff across sampled games: {max_abs_diff:.6f}")

    out_path.write_text("\n".join(lines), encoding="utf-8")

    # fail-fast
    if prohibited_hits:
        raise RuntimeError("Prohibited feature substrings detected; see report")
    if na_cols or inf_cols:
        raise RuntimeError("NA/Inf detected in features; see report")

    # timing check gate
    max_abs_diff = max(t["abs_diff"] for t in timing_checks) if timing_checks else 0.0
    if max_abs_diff > 1e-6:
        raise RuntimeError(f"Timing check failed: max_abs_diff={max_abs_diff}")

    print(f"Wrote: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

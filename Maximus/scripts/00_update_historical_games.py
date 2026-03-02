"""Update historical games parquet using nba_api (Option 1).

Goal:
- Append newly completed games to data_v4/raw/historical_games_full.parquet
- Keep schema compatible with Maximus

This script is intentionally conservative:
- Dedupe by game_id
- Only adds games strictly after the current max game_date
- Uses retries/backoff for nba_api 403/429/timeouts

Outputs:
- Updates: data_v4/raw/historical_games_full.parquet (atomic)
- Writes: Maximus/artifacts/HISTORICAL_GAMES_UPDATE.json
"""

from __future__ import annotations

import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def _scoreboardv2_worker(date_str: str, out_path: str) -> None:
    """Worker for multiprocessing hard-timeout wrapper.

    Writes a parquet with two columns: name (dataset name) and payload (pickled bytes).

    We avoid mp.Queue with DataFrames to keep pickling simple.
    """

    from nba_api.stats.endpoints import scoreboardv2

    sb = scoreboardv2.ScoreboardV2(game_date=date_str, league_id="00")
    sets = sb.data_sets
    dfs = sb.get_data_frames()

    # Serialize each DataFrame to parquet bytes via pyarrow
    import io

    rows = []
    for s, df in zip(sets, dfs):
        name = getattr(s, "name", None) or getattr(s, "dataset_name", None) or str(s)
        buf = io.BytesIO()
        df.to_parquet(buf, index=False)
        rows.append({"name": name, "payload": buf.getvalue()})

    pd.DataFrame(rows).to_parquet(out_path, index=False)


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = REPO_ROOT / "data_v4" / "raw" / "historical_games_full.parquet"


def _season_for_date(d: pd.Timestamp) -> str:
    # NBA season starts ~Oct; anything before July is prior season end.
    y = int(d.year)
    m = int(d.month)
    if m >= 10:
        return f"{y}-{str(y+1)[-2:]}"
    return f"{y-1}-{str(y)[-2:]}"


def _with_headers():
    # nba_api uses requests under the hood; update the global STATS_HEADERS.
    # This is version-stable across nba_api releases.
    from nba_api.stats.library import http

    http.STATS_HEADERS.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.nba.com/",
            "Origin": "https://www.nba.com",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "application/json, text/plain, */*",
            "Connection": "keep-alive",
        }
    )


def _fetch_leaguegamefinder(season: str, max_retries: int = 8) -> pd.DataFrame:
    from nba_api.stats.endpoints import leaguegamefinder

    _with_headers()

    delay = 1.0
    last_err = None

    for attempt in range(1, max_retries + 1):
        try:
            lgf = leaguegamefinder.LeagueGameFinder(season_nullable=season, league_id_nullable="00")
            df = lgf.get_data_frames()[0]
            return df
        except Exception as e:
            last_err = e
            # exponential backoff with jitter
            sleep_s = delay + random.uniform(0.0, 0.5)
            print(f"nba_api error attempt {attempt}/{max_retries}: {type(e).__name__}: {e} -> sleep {sleep_s:.2f}s")
            time.sleep(sleep_s)
            delay = min(delay * 2.0, 30.0)

    raise RuntimeError(f"Failed to fetch leaguegamefinder for season={season}") from last_err


def _collapse_to_games(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse team-level rows to one row per game_id.

    leaguegamefinder returns one row per team per game.
    We reconstruct home/away by MATCHUP string.
    """

    df = df.copy()
    df["GAME_ID"] = df["GAME_ID"].astype(str)

    out = {}
    for _, r in df.iterrows():
        gid = str(r.get("GAME_ID"))
        matchup = str(r.get("MATCHUP") or "")
        team = str(r.get("TEAM_ABBREVIATION") or "")
        pts = r.get("PTS")
        game_date = r.get("GAME_DATE")

        rec = out.get(gid) or {
            "game_id": gid,
            "game_date": game_date,
            "home_tri": None,
            "away_tri": None,
            "home_pts": None,
            "away_pts": None,
        }

        if " vs " in matchup:
            # this row is home team
            rec["home_tri"] = team
            rec["home_pts"] = pts
        elif " @ " in matchup:
            # this row is away team
            rec["away_tri"] = team
            rec["away_pts"] = pts

        out[gid] = rec

    games = pd.DataFrame(out.values())

    # normalize dates
    games["game_date"] = pd.to_datetime(games["game_date"], utc=True, errors="coerce")

    # drop incomplete rows
    games = games.dropna(subset=["game_date", "home_tri", "away_tri", "home_pts", "away_pts"])

    games["home_pts"] = games["home_pts"].astype(int)
    games["away_pts"] = games["away_pts"].astype(int)
    games["season"] = games["game_date"].apply(_season_for_date)
    games["margin"] = games["home_pts"] - games["away_pts"]
    games["total"] = games["home_pts"] + games["away_pts"]

    return games


def _fetch_scoreboard_for_date(game_date: pd.Timestamp, max_retries: int = 3) -> list[pd.DataFrame]:
    """Fetch ScoreboardV2 datasets for a date.

    Direct call (no multiprocessing). In this environment, ScoreboardV2 is fast and
    returns empty results on off-days.
    """

    from nba_api.stats.endpoints import scoreboardv2

    _with_headers()

    delay = 0.8
    last_err = None

    date_str = game_date.strftime("%m/%d/%Y")

    for attempt in range(1, max_retries + 1):
        try:
            sb = scoreboardv2.ScoreboardV2(game_date=date_str, league_id="00")
            return sb.get_data_frames()
        except Exception as e:
            last_err = e
            sleep_s = delay + random.uniform(0.0, 0.4)
            print(
                f"nba_api scoreboard error {date_str} attempt {attempt}/{max_retries}: {type(e).__name__}: {e} -> sleep {sleep_s:.2f}s",
                flush=True,
            )
            time.sleep(sleep_s)
            delay = min(delay * 2.0, 15.0)

    raise RuntimeError(f"Failed to fetch scoreboardv2 for date={date_str}") from last_err


def _games_from_scoreboard(game_date: pd.Timestamp, dfs: list[pd.DataFrame]) -> pd.DataFrame:
    """Convert ScoreboardV2 frames into game rows.

    This nba_api version doesn't provide stable dataset names, so we detect the
    needed frames by their columns.
    """

    header_df = None
    linescore_df = None

    for df in dfs:
        cols = set(df.columns)
        if {"GAME_ID", "GAME_STATUS_ID", "HOME_TEAM_ID", "VISITOR_TEAM_ID"}.issubset(cols):
            header_df = df
        if {"GAME_ID", "TEAM_ID", "TEAM_ABBREVIATION", "PTS"}.issubset(cols):
            # choose the richer linescore (has TEAM_ABBREVIATION + PTS)
            if linescore_df is None or len(df.columns) > len(linescore_df.columns):
                linescore_df = df

    if header_df is None or linescore_df is None:
        return pd.DataFrame(columns=["game_id", "game_date", "home_tri", "away_tri", "home_pts", "away_pts"])

    gh = header_df.copy()
    gh["game_id"] = gh["GAME_ID"].astype(str)

    # final only
    gh = gh[gh["GAME_STATUS_ID"] == 3]
    if len(gh) == 0:
        return pd.DataFrame(columns=["game_id", "game_date", "home_tri", "away_tri", "home_pts", "away_pts"])

    ls = linescore_df.copy()
    ls["game_id"] = ls["GAME_ID"].astype(str)

    out_rows = []
    for _, r in gh.iterrows():
        gid = str(r["game_id"])
        ht_id = int(r["HOME_TEAM_ID"])
        vt_id = int(r["VISITOR_TEAM_ID"])

        rows = ls[ls["game_id"] == gid]
        home = rows[rows["TEAM_ID"] == ht_id]
        away = rows[rows["TEAM_ID"] == vt_id]
        if len(home) != 1 or len(away) != 1:
            continue

        out_rows.append(
            {
                "game_id": gid,
                "game_date": game_date,
                "home_tri": str(home.iloc[0]["TEAM_ABBREVIATION"]),
                "away_tri": str(away.iloc[0]["TEAM_ABBREVIATION"]),
                "home_pts": int(home.iloc[0]["PTS"]),
                "away_pts": int(away.iloc[0]["PTS"]),
            }
        )

    return pd.DataFrame(out_rows)


def main() -> int:
    if not SRC_PATH.exists():
        raise FileNotFoundError(f"Missing source parquet: {SRC_PATH}")

    cur = pd.read_parquet(SRC_PATH)
    cur["game_date"] = pd.to_datetime(cur["game_date"], utc=True, errors="raise")
    max_date = cur["game_date"].max()
    print(f"Current max game_date: {max_date}")

    # Crawl scoreboard day-by-day from (max_date+1) to today.
    start = (max_date + pd.Timedelta(days=1)).normalize()
    today = pd.Timestamp.now(tz="UTC").normalize()

    # Don't crawl forever; if the season is over, this would be wasted calls.
    max_days = 21
    end = min(today, start + pd.Timedelta(days=max_days - 1))

    if start > today:
        print("No days to crawl (already up to date).")
        return 0

    cache_dir = REPO_ROOT / "Maximus" / "data" / "raw" / "api_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    all_new = []
    print(f"Crawling scoreboard dates: {start.date()} -> {end.date()} (max_days={max_days})", flush=True)

    d = start
    i = 0
    while d <= end:
        cache_path = cache_dir / f"scoreboardv2_{d.strftime('%Y%m%d')}.parquet"
        def fetch_and_cache() -> pd.DataFrame:
            dfs = _fetch_scoreboard_for_date(d)
            games_d = _games_from_scoreboard(d, dfs)
            games_d.to_parquet(cache_path, index=False)
            # polite sleep
            time.sleep(0.4 + random.uniform(0.0, 0.3))
            return games_d

        if cache_path.exists():
            data = pd.read_parquet(cache_path)
            required = {"game_id", "game_date", "home_tri", "away_tri", "home_pts", "away_pts"}
            if len(data) == 0 or not required.issubset(set(data.columns)):
                # self-heal stale/bad cache from previous buggy runs
                data = fetch_and_cache()
        else:
            data = fetch_and_cache()

        if i % 3 == 0:
            print(f"  {d.date()} games_found={len(data)}", flush=True)

        if len(data):
            all_new.append(data)

        d = d + pd.Timedelta(days=1)
        i += 1

    if all_new:
        new = pd.concat(all_new, ignore_index=True)
    else:
        new = pd.DataFrame(columns=["game_id", "game_date", "home_tri", "away_tri", "home_pts", "away_pts"])

    # normalize + compute targets
    if len(new):
        new["game_date"] = pd.to_datetime(new["game_date"], utc=True, errors="coerce")
        new = new.dropna(subset=["game_id", "game_date", "home_tri", "away_tri", "home_pts", "away_pts"]).copy()
        new["season"] = new["game_date"].apply(_season_for_date)
        new["home_pts"] = new["home_pts"].astype(int)
        new["away_pts"] = new["away_pts"].astype(int)
        new["margin"] = new["home_pts"] - new["away_pts"]
        new["total"] = new["home_pts"] + new["away_pts"]

    # only new games beyond current max_date
    new = new[new["game_date"] > max_date].copy()

    season = "AUTO"

    before = len(cur)
    if len(new) == 0:
        print("No new games found.")
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "season": season,
            "max_date_before": str(max_date),
            "added": 0,
        }
        (REPO_ROOT / "Maximus" / "artifacts" / "HISTORICAL_GAMES_UPDATE.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        return 0

    merged = pd.concat([cur, new], ignore_index=True)
    merged = merged.drop_duplicates(subset=["game_id"], keep="last")

    # keep sorted
    merged = merged.sort_values(["game_date", "game_id"]).reset_index(drop=True)

    tmp = SRC_PATH.with_suffix(".parquet.tmp")
    merged.to_parquet(tmp, index=False)
    tmp.replace(SRC_PATH)

    after = len(merged)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "season": season,
        "max_date_before": str(max_date),
        "max_date_after": str(merged["game_date"].max()),
        "rows_before": before,
        "rows_after": after,
        "added": int(after - before),
        "n_new_candidates": int(len(new)),
    }
    out_path = REPO_ROOT / "Maximus" / "artifacts" / "HISTORICAL_GAMES_UPDATE.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(json.dumps(payload, indent=2))
    print(f"Updated: {SRC_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

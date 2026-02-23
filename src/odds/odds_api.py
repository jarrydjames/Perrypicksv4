from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

import requests

# Check if we should use the local Odds API
USE_LOCAL_ODDS_API = os.getenv("USE_LOCAL_ODDS_API", "").lower() in ("true", "1", "yes")

if USE_LOCAL_ODDS_API:
    # Import the local client which has the same interface
    from src.odds.local_odds_client import (
        fetch_nba_odds_snapshot as _local_fetch_nba_odds_snapshot,
        OddsAPIMarketSnapshot as _LocalOddsAPIMarketSnapshot,
        OddsAPIError as _LocalOddsAPIError,
        health_check as _local_health_check,
    )
    logger.info("Using local Odds API (http://localhost:8890)")


ODDS_API_BASE = "https://api.the-odds-api.com/v4"


@dataclass(frozen=True)
class OddsAPIMarketSnapshot:
    # Main markets (full game)
    total_points: Optional[float]
    total_over_odds: Optional[int]
    total_under_odds: Optional[int]

    spread_home: Optional[float]  # sportsbook convention: home line (e.g. -3.5)
    spread_home_odds: Optional[int]
    spread_away_odds: Optional[int]

    moneyline_home: Optional[int]
    moneyline_away: Optional[int]

    # Team totals (if supported by book/plan)
    team_total_home: Optional[float]
    team_total_home_over_odds: Optional[int]
    team_total_home_under_odds: Optional[int]

    team_total_away: Optional[float]
    team_total_away_over_odds: Optional[int]
    team_total_away_under_odds: Optional[int]

    bookmaker: Optional[str] = None
    last_update: Optional[str] = None


class OddsAPIError(RuntimeError):
    pass



def _log_odds_call(reason: str, endpoint: str, **kwargs) -> None:
    """Log odds API call with reason + endpoint + params."""
    logger.info(f"Odds API call - Reason: {reason}, Endpoint: {endpoint}, Params: {kwargs}")


def get_api_key() -> str:
    # Streamlit Cloud: use secrets.
    # Locally: allow env var.
    key = os.getenv("ODDS_API_KEY")
    if key:
        return key

    # Avoid importing streamlit at module import time (cloud safety)
    try:
        import streamlit as st  # type: ignore

        if "ODDS_API_KEY" in st.secrets:
            return str(st.secrets["ODDS_API_KEY"]).strip()
    except Exception:
        pass

    raise OddsAPIError(
        "Missing ODDS_API_KEY. Add it to Streamlit Secrets (ODDS_API_KEY) or set env var ODDS_API_KEY."
    )


def _american_from_price(price: Any) -> Optional[int]:
    if price is None:
        return None
    try:
        return int(price)
    except Exception:
        return None


def fetch_nba_odds_snapshot(
    *,
    home_name: str,
    away_name: str,
    regions: str = "us",
    markets: str = "h2h,spreads,totals,team_totals",
    odds_format: str = "american",
    date_format: str = "iso",
    preferred_book: Optional[str] = None,
    timeout_s: int = 45,  # CRITICAL FIX: Increased from 10s to match local API
) -> OddsAPIMarketSnapshot:
    """Fetch a *single* consolidated odds snapshot for an NBA matchup.

    We deliberately keep this narrow:
    - One endpoint call.
    - We pick ONE bookmaker (either preferred_book or the first available) to avoid mixing books.

    Team totals:
    - If available, we parse market key `team_totals` where each outcome usually has:
      - name: Over/Under
      - description: team name
      - point: team total line

    Local Odds API:
    - If USE_LOCAL_ODDS_API=true, uses the local Odds API (free ESPN odds)
    - Otherwise falls back to the-odds-api.com (requires API key)
    """
    # Use local Odds API if available
    if USE_LOCAL_ODDS_API:
        logger.info(f"Using local Odds API for {away_name} @ {home_name}")
        local_snapshot = _local_fetch_nba_odds_snapshot(
            home_name=home_name,
            away_name=away_name,
            regions=regions,
            markets=markets,
            odds_format=odds_format,
            date_format=date_format,
            preferred_book=preferred_book,
            timeout_s=timeout_s,
        )
        # Convert to our OddsAPIMarketSnapshot format
        return OddsAPIMarketSnapshot(
            total_points=local_snapshot.total_points,
            total_over_odds=local_snapshot.total_over_odds,
            total_under_odds=local_snapshot.total_under_odds,
            spread_home=local_snapshot.spread_home,
            spread_home_odds=local_snapshot.spread_home_odds,
            spread_away_odds=local_snapshot.spread_away_odds,
            moneyline_home=local_snapshot.moneyline_home,
            moneyline_away=local_snapshot.moneyline_away,
            team_total_home=local_snapshot.team_total_home,
            team_total_home_over_odds=local_snapshot.team_total_home_over_odds,
            team_total_home_under_odds=local_snapshot.team_total_home_under_odds,
            team_total_away=local_snapshot.team_total_away,
            team_total_away_over_odds=local_snapshot.team_total_away_over_odds,
            team_total_away_under_odds=local_snapshot.team_total_away_under_odds,
            bookmaker=local_snapshot.bookmaker,
            last_update=local_snapshot.last_update,
        )

    # Fall back to external API
    key = get_api_key()

    url = f"{ODDS_API_BASE}/sports/basketball_nba/odds"
    params = {
        "apiKey": key,
        "regions": regions,
        "markets": markets,
        "oddsFormat": odds_format,
        "dateFormat": date_format,
    }

    def _do_request(p: Dict[str, Any]) -> requests.Response:
        _log_odds_call(reason="fresh_request", endpoint=url, **p)
        return requests.get(url, params=p, timeout=timeout_s)

    # CRITICAL FIX: Add retry logic for transient failures
    max_retries = 3
    retry_delay = 2
    r = None

    for attempt in range(max_retries):
        try:
            r = _do_request(params)

            if r.status_code == 429:
                # Rate limited - wait and retry
                wait_time = retry_delay * (attempt + 1)
                logger.warning(f"Odds API rate limited, waiting {wait_time}s")
                time.sleep(wait_time)
                continue

            break  # Success or non-retryable error
        except (requests.Timeout, requests.ConnectionError) as e:
            if attempt < max_retries - 1:
                wait_time = retry_delay * (attempt + 1)
                logger.warning(f"Odds API network error ({type(e).__name__}), retrying in {wait_time}s")
                time.sleep(wait_time)
                continue
            raise OddsAPIError(f"Odds API network error after {max_retries} retries: {e}")

    if r is None:
        raise OddsAPIError("Odds API failed - no response")

    if r.status_code != 200:
        # Fail-soft: if team_totals market isn't supported on this endpoint/plan,
        # retry once without it so we can still autofill totals/spreads/moneylines.
        try:
            err = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        except Exception:
            err = {}

        msg = str(err.get("message") or r.text or "")
        code = str(err.get("error_code") or "")

        if r.status_code == 422 and code == "INVALID_MARKET" and "team_totals" in msg:
            params_no_tt = dict(params)
            params_no_tt["markets"] = ",".join(
                [m for m in str(params.get("markets") or "").split(",") if m.strip() and m.strip() != "team_totals"]
            )
            r = _do_request(params_no_tt)

        if r.status_code != 200:
            raise OddsAPIError(f"Odds API error: HTTP {r.status_code}: {r.text[:300]}")

    events = r.json()
    if not isinstance(events, list):
        raise OddsAPIError("Odds API response not a list")

    def _norm(s: str) -> str:
        return " ".join(
            "".join(ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in s).split()
        )

    hn = _norm(home_name)
    an = _norm(away_name)

    def _team_score(want: str, got: str) -> float:
        # Ensure both are strings
        if not want or not got:
            return 0.0
        want_str = str(want) if not isinstance(want, str) else want
        got_str = str(got) if not isinstance(got, str) else got
        
        if want_str == got_str:
            return 10.0
        if want_str in got_str or got_str in want_str:
            return 8.0
        want_tokens = set(want_str.split())
        got_tokens = set(got_str.split())
        if not want_tokens or not got_tokens:
            return 0.0
        overlap = len(want_tokens & got_tokens)
        return 3.0 * (overlap / max(len(want_tokens), len(got_tokens)))

    best = None
    best_swapped = False
    best_score = 0.0

    for ev in events:
        try:
            h = _norm(str(ev.get("home_team", "")))
            a = _norm(str(ev.get("away_team", "")))

            score_normal = _team_score(hn, h) + _team_score(an, a)
            score_swapped = _team_score(hn, a) + _team_score(an, h)

            if score_normal > best_score:
                best = ev
                best_swapped = False
                best_score = score_normal
            if score_swapped > best_score:
                best = ev
                best_swapped = True
                best_score = score_swapped
        except Exception:
            continue

    # Threshold: require at least some similarity on both teams.
    if best is None or best_score < 6.0:
        sample = []
        for ev in events[:8]:
            try:
                sample.append(f"{ev.get('away_team','?')} @ {ev.get('home_team','?')}")
            except Exception:
                continue
        raise OddsAPIError(
            f"No odds match found for {away_name} @ {home_name}. "
            f"Sample available games: {', '.join(sample)}"
        )

    match = best
    swapped = best_swapped

    bookmakers = match.get("bookmakers") or []
    if not bookmakers:
        raise OddsAPIError("No bookmakers in odds response")

    chosen = None
    if preferred_book:
        for b in bookmakers:
            if str(b.get("key", "")).strip().lower() == preferred_book.strip().lower():
                chosen = b
                break

    if chosen is None:
        chosen = bookmakers[0]

    book_key = str(chosen.get("key") or "") or None
    last_update = str(chosen.get("last_update") or "") or None

    total_points = None
    total_over_odds = None
    total_under_odds = None

    spread_home = None
    spread_home_odds = None
    spread_away_odds = None

    ml_home = None
    ml_away = None

    team_total_home = None
    team_total_home_over_odds = None
    team_total_home_under_odds = None

    team_total_away = None
    team_total_away_over_odds = None
    team_total_away_under_odds = None

    def _is_same_team(name_a: str, name_b: str) -> bool:
        a = _norm(name_a)
        b = _norm(name_b)
        if not a or not b:
            return False
        return a == b or a in b or b in a

    for m in chosen.get("markets") or []:
        mk = str(m.get("key") or "")

        if mk == "totals":
            # outcomes: Over/Under with point
            for o in m.get("outcomes") or []:
                name = str(o.get("name") or "")
                point = o.get("point")
                price = _american_from_price(o.get("price"))
                if point is not None:
                    total_points = float(point)
                if name.lower() == "over":
                    total_over_odds = price
                elif name.lower() == "under":
                    total_under_odds = price

        elif mk == "spreads":
            # outcomes by team name with point (spread)
            for o in m.get("outcomes") or []:
                name = str(o.get("name") or "")
                point = o.get("point")
                price = _american_from_price(o.get("price"))
                if point is None:
                    continue

                if _is_same_team(name, home_name):
                    spread_home = float(point)
                    spread_home_odds = price
                elif _is_same_team(name, away_name):
                    spread_away_odds = price

        elif mk == "team_totals":
            # outcomes: Over/Under, but team is in `description`
            for o in m.get("outcomes") or []:
                side = str(o.get("name") or "").strip().lower()  # over/under
                team = str(o.get("description") or "").strip()
                point = o.get("point")
                price = _american_from_price(o.get("price"))
                if point is None or not team:
                    continue

                # If API home/away swapped relative to our names, that doesn't matter here,
                # because we're matching by actual team names.
                if _is_same_team(team, home_name):
                    team_total_home = float(point)
                    if side == "over":
                        team_total_home_over_odds = price
                    elif side == "under":
                        team_total_home_under_odds = price

                elif _is_same_team(team, away_name):
                    team_total_away = float(point)
                    if side == "over":
                        team_total_away_over_odds = price
                    elif side == "under":
                        team_total_away_under_odds = price

        elif mk == "h2h":
            for o in m.get("outcomes") or []:
                name = str(o.get("name") or "")
                price = _american_from_price(o.get("price"))

                if _is_same_team(name, home_name):
                    ml_home = price
                elif _is_same_team(name, away_name):
                    ml_away = price

    return OddsAPIMarketSnapshot(
        total_points=total_points,
        total_over_odds=total_over_odds,
        total_under_odds=total_under_odds,
        spread_home=spread_home,
        spread_home_odds=spread_home_odds,
        spread_away_odds=spread_away_odds,
        moneyline_home=ml_home,
        moneyline_away=ml_away,
        team_total_home=team_total_home,
        team_total_home_over_odds=team_total_home_over_odds,
        team_total_home_under_odds=team_total_home_under_odds,
        team_total_away=team_total_away,
        team_total_away_over_odds=team_total_away_over_odds,
        team_total_away_under_odds=team_total_away_under_odds,
        bookmaker=book_key,
        last_update=last_update,
    )

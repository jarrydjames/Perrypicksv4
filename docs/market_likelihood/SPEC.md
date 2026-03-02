# Live Book-Implied Bet Likelihood Engine — Prototype Spec (v0)

## Purpose
Compute **the sportsbook-implied probability that an ORIGINAL ticket wins**, using only live market data:
- Original ticket: (bet type, side, line, odds)
- Live market snapshot: (current line + both sides odds)
- Optional cached history of snapshots (for trend + slope)

**Explicit non-goals (v0):**
- Do **not** use model probabilities.
- Do **not** compute true cashout EV (no cashout quotes).
- Do **not** ship production-grade execution yet.

---

## Inputs
### 1) BetTicket
A canonical representation of the *original recommendation*.

Minimum fields:
- `bet_id`: stable id
- `game_id`
- `bet_type`: `spread | total | team_total`
- `side`: `home | away | over | under`
- `line`: float (original ticket line)
- `odds_american`: int (original ticket odds)
- `created_at_utc`
- `discord_message_id` (optional; only needed if editing messages)

### 2) MarketSnapshot
A single market snapshot at time `t`.

Minimum fields:
- `game_id`
- `timestamp_utc`
- `bet_type`
- `line_current`: float
- `odds_fav_american`: int
- `odds_dog_american`: int
- `bookmaker`: str

Notes:
- For spread/team_total: snapshot should represent *one line* with two prices.
- For totals: line is total, odds are over/under.

---

## Core Computation
### Step A — De-vig
Convert both American odds to implied probabilities and remove vig:
- `p1_raw`, `p2_raw`
- `p1_fair = p1_raw / (p1_raw + p2_raw)`
- `p2_fair = 1 - p1_fair`

Output: fair probability for each side at the **current line**.

### Step B — Translate current-line probability → original-ticket probability
We need a bridge from current line `L_now` to original line `L_orig`.

We will prototype **two estimators** and optionally blend them.

#### Approach A (recommended baseline): Normal margin model
Assume final outcome variable is approximately Normal around a market-implied mean.

- Spread: final margin `M = home - away` ~ Normal(μ, σ)
  - market implies μ ≈ -`spread_home_current`
- Totals: final total `T` ~ Normal(μ, σ)
  - market implies μ ≈ `total_current`
- Team totals: team points ~ Normal(μ, σ)

σ (prototype options):
1. Fixed σ by bet type + time remaining (simple, stable)
2. Dynamic σ inferred from recent line volatility (uses snapshot history)

Compute probability that the original condition holds (e.g., spread cover, over/under).

#### Approach B: Local line-slope model
Estimate `dp/dL` from recent history of (line, fair_prob) pairs.

Then:
- `p(orig) ≈ p(now) + dp/dL * (L_orig - L_now)`

Used when sufficient movement exists.

#### Output
A `ProbabilityEstimate` with:
- `p_hit`: float [0,1]
- `p_band`: optional (low/high)
- `trend_2m`: delta over last N updates
- `momentum`: slope over last K updates
- `status_tier`: Strong/OK/Watch/Danger/Exit
- `explain`: human-readable summary fields

---

## Status Tiers (prototype defaults)
Emotion-first tiers (not “truth”):
- Strong: `p >= 0.70`
- OK: `0.55 <= p < 0.70`
- Watch: `0.40 <= p < 0.55`
- Danger: `0.25 <= p < 0.40`
- Exit Window: `p < 0.25`

Hysteresis:
- Entering a worse tier requires 2 consecutive updates below threshold.
- Exiting requires crossing back by +0.05.

---

## Discord UX (prototype)
Primary: **edit one message per ticket**.

Fallback (if editing isn’t possible): periodic summary message + slash query.

Fields to show:
- Ticket (original)
- Current market
- Probability + trend arrow
- Move vs ticket (points)
- Tier emoji
- Mini sparkline (last ~7 updates)

Alerts:
- Only on tier crossings (with cooldown).

---

## Update cadence
- Compute every 30s (matches odds snapshots)
- Discord edit every 60s (rate limit friendly)

---

## Prototype architecture modules
- `devig.py` (odds → fair probs)
- `models/` (Approach A + B)
- `state.py` (rolling window, hysteresis, alert eligibility)
- `discord_view.py` (embed payload generator)



## Discord message editing (Option A)
To support non-spammy continuous updates, the system should **edit a single Discord message** per ticket.

Implementation notes:
- When creating the initial webhook message, use `?wait=true` so Discord returns JSON with `id`.
- Store that `message_id` alongside the ticket (DB or lightweight store).
- Use `DISCORD_LIVE_TRACKING_WEBHOOK` (preferred) for the progress/tracking channel (fallback: `DISCORD_WEBHOOK_URL`).
- Update via webhook edit endpoint:
  - `PATCH {webhook_url}/messages/{message_id}`

Caveats:
- Only messages created by the same webhook can be edited.
- Rate-limit updates (recommend: compute every 30s, edit every 60s).


## Tracking odds source policy (HARD RULE)
For *tracking* (likelihood updates), the system must **only** use the local composite Odds API:
- Call `src.odds.local_odds_client.fetch_nba_odds_snapshot` directly.

Do **not** call `src.odds.odds_api.fetch_nba_odds_snapshot` from tracking code, because it may fall back to external providers.

External odds providers may be used for *prediction-time fallback only*.

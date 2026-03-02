"""
PerryPicks Dashboard API

FastAPI backend for the PerryPicks dashboard.
"""

import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

# Load .env from project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

from fastapi import FastAPI, Depends, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

# Add project root to path
sys.path.insert(0, str(PROJECT_ROOT))

from .database import (
    init_db,
    get_db,
    Game,
    Prediction,
    BettingRecommendation,
    GhostBet,
    GhostBettorConfig,
    PerformanceSnapshot,
    SystemConfig,
    LiveBetSnapshot,
    TriggerType,
    BetType,
    BetStatus,
    PredictionStatus,
)
from .ghost_bettor import GhostBettor, get_ghost_bettor

# Initialize FastAPI
app = FastAPI(
    title="PerryPicks Dashboard API",
    description="Backend API for PerryPicks prediction tracking dashboard",
    version="1.0.0",
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============ Pydantic Models ============

class GameResponse(BaseModel):
    id: int
    nba_id: Optional[str]
    game_date: datetime
    home_team: str
    away_team: str
    home_team_name: Optional[str]
    away_team_name: Optional[str]
    game_time: Optional[datetime]
    final_home_score: Optional[int]
    final_away_score: Optional[int]
    final_total: Optional[float]
    final_margin: Optional[float]
    game_status: Optional[str]

    class Config:
        from_attributes = True


class PredictionResponse(BaseModel):
    id: int
    game_id: int
    trigger_type: str
    h1_home: Optional[int]
    h1_away: Optional[int]
    pred_total: Optional[float]
    pred_margin: Optional[float]
    pred_winner: Optional[str]
    home_win_prob: Optional[float]
    status: str
    actual_total: Optional[float]
    actual_margin: Optional[float]
    actual_winner: Optional[str]
    total_error: Optional[float]
    margin_error: Optional[float]
    winner_correct: Optional[bool]
    posted_to_discord: bool
    created_at: datetime

    class Config:
        from_attributes = True


class GhostBetResponse(BaseModel):
    id: int
    game_id: int
    bet_type: str
    pick: str
    line: Optional[float]
    odds: Optional[int]
    edge: Optional[float]
    probability: Optional[float]
    confidence_tier: Optional[str]
    bet_amount: float
    potential_payout: Optional[float]
    result: str
    actual_payout: Optional[float]
    created_at: datetime
    resolved_at: Optional[datetime]

    class Config:
        from_attributes = True


class GhostBettorConfigResponse(BaseModel):
    starting_bankroll: float
    current_bankroll: float
    default_bet_amount: float
    total_min_edge: Optional[float] = None
    total_min_prob: float
    spread_min_edge: Optional[float] = None
    spread_min_prob: float
    ml_min_edge: Optional[float] = None
    ml_min_prob: float
    max_bets_per_game: Optional[int] = None
    max_bets_per_day: Optional[int] = None
    is_active: bool

    class Config:
        from_attributes = True


class GhostBettorConfigUpdate(BaseModel):
    starting_bankroll: Optional[float] = None
    current_bankroll: Optional[float] = None
    default_bet_amount: Optional[float] = None
    total_min_edge: Optional[float] = None
    total_min_prob: Optional[float] = None
    spread_min_edge: Optional[float] = None
    spread_min_prob: Optional[float] = None
    ml_min_edge: Optional[float] = None
    ml_min_prob: Optional[float] = None
    max_bets_per_game: Optional[int] = None
    max_bets_per_day: Optional[int] = None
    is_active: Optional[bool] = None


class GhostBettorStats(BaseModel):
    period_days: int
    total_bets: int
    won: int
    lost: int
    pending: int
    push: int
    win_rate: float
    total_wagered: float
    total_return: float
    profit_loss: float
    roi: float
    current_bankroll: float
    starting_bankroll: float
    by_type: dict
    by_tier: dict


class ManualPredictionRequest(BaseModel):
    game_id: str  # NBA game ID
    trigger_type: str  # pregame, halftime, q3_5min
    post_to_discord: bool = False


class PerformanceMetrics(BaseModel):
    total_predictions: int
    correct_predictions: int
    pending_predictions: int
    win_rate: float
    total_mae: Optional[float]
    margin_mae: Optional[float]


# ============ Startup ============

@app.on_event("startup")
def startup():
    """Initialize database on startup."""
    init_db()


# ============ Games Endpoints ============

@app.get("/api/games", response_model=List[GameResponse])
def get_games(
    date: Optional[str] = Query(None, description="Filter by date (YYYY-MM-DD)"),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, le=100),
    db: Session = Depends(get_db),
):
    """Get games, optionally filtered by date."""
    query = db.query(Game)

    if date:
        date_obj = datetime.strptime(date, "%Y-%m-%d")
        query = query.filter(
            Game.game_date >= date_obj,
            Game.game_date < date_obj + timedelta(days=1)
        )

    if status:
        query = query.filter(Game.game_status == status)

    return query.order_by(Game.game_date.desc()).limit(limit).all()


@app.get("/api/games/today", response_model=List[GameResponse])
def get_todays_games(db: Session = Depends(get_db)):
    """Get today's games.
    
    IMPORTANT: Games are stored in UTC but we query in local time.
    We need to convert game_date from UTC to local time before comparing.
    """
    from datetime import date as date_type, datetime as dt
    from sqlalchemy import func
    
    today = date_type.today()
    
    # Get games where game_date (UTC) converted to local time is today
    # SQLite doesn't have timezone support, so we handle this differently:
    # 1. Get all games from a wider date range (today ± 1 day)
    # 2. Filter by checking if the local date matches today
    
    # Start date: yesterday at midnight UTC
    start_date_utc = dt(today.year, today.month, today.day) - timedelta(days=1)
    # End date: tomorrow at midnight UTC
    end_date_utc = dt(today.year, today.month, today.day) + timedelta(days=2)
    
    # Get all games in this range
    games = db.query(Game).filter(
        Game.game_date >= start_date_utc,
        Game.game_date < end_date_utc
    ).all()
    
    # Filter to only games that are on the local date
    # Convert UTC to local time and check date
    games_today = []
    for game in games:
        if game.game_date:
            # Convert UTC to local time (CST = UTC-6)
            local_time = game.game_date - timedelta(hours=6)
            local_date = local_time.date()
            if local_date == today:
                games_today.append(game)
    
    return games_today


@app.get("/api/games/{game_id}", response_model=GameResponse)
def get_game(game_id: int, db: Session = Depends(get_db)):
    """Get a specific game."""
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return game


# ============ Predictions Endpoints ============

@app.get("/api/predictions")
def get_predictions(
    game_id: Optional[int] = None,
    trigger_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(50, le=100),
    db: Session = Depends(get_db),
):
    """Get predictions with game info, optionally filtered."""
    query = db.query(Prediction)

    if game_id:
        query = query.filter(Prediction.game_id == game_id)
    if trigger_type:
        query = query.filter(Prediction.trigger_type == trigger_type)
    if status:
        query = query.filter(Prediction.status == status)

    predictions = query.order_by(Prediction.created_at.desc()).limit(limit).all()

    # Enrich with game info
    results = []
    for pred in predictions:
        game = db.query(Game).filter(Game.id == pred.game_id).first()
        results.append({
            "id": pred.id,
            "game_id": pred.game_id,
            "nba_id": game.nba_id if game else None,
            "home_team": game.home_team_name or game.home_team if game else None,
            "away_team": game.away_team_name or game.away_team if game else None,
            "game_status": game.game_status if game else None,
            "trigger_type": pred.trigger_type.value if hasattr(pred.trigger_type, 'value') else str(pred.trigger_type),
            "h1_home": pred.h1_home,
            "h1_away": pred.h1_away,
            "pred_total": pred.pred_total,
            "pred_margin": pred.pred_margin,
            "pred_winner": pred.pred_winner,
            "home_win_prob": pred.home_win_prob,
            "status": pred.status.value if hasattr(pred.status, 'value') else str(pred.status),
            "actual_total": pred.actual_total,
            "actual_margin": pred.actual_margin,
            "actual_winner": pred.actual_winner,
            "winner_correct": pred.winner_correct,
            "posted_to_discord": pred.posted_to_discord,
            "created_at": pred.created_at.isoformat() if pred.created_at else None,
        })

    return results


@app.get("/api/triggers/pending")
def get_pending_triggers(db: Session = Depends(get_db)):
    """Get pending halftime triggers for today's games."""
    from datetime import date as date_type
    today = date_type.today()

    # Get today's games that haven't triggered yet
    from sqlalchemy import func
    games = db.query(Game).filter(
        func.date(Game.game_date) == today,
        Game.game_status != "Final",
    ).order_by(Game.game_date).all()

    triggers = []
    for game in games:
        # Check if this game already has a halftime prediction
        existing_pred = db.query(Prediction).filter(
            Prediction.game_id == game.id,
            Prediction.trigger_type == TriggerType.HALFTIME
        ).first()

        # Determine trigger status
        if existing_pred:
            trigger_status = "fired"
            prediction_id = existing_pred.id
        elif "Halftime" in (game.game_status or ""):
            trigger_status = "ready"
            prediction_id = None
        else:
            trigger_status = "pending"
            prediction_id = None

        triggers.append({
            "game_id": game.id,
            "nba_id": game.nba_id,
            "home_team": game.home_team_name or game.home_team,
            "away_team": game.away_team_name or game.away_team,
            "game_time": game.game_time.isoformat() if game.game_time else None,
            "game_status": game.game_status,
            "period": game.period,
            "clock": game.clock,
            "home_score": game.final_home_score or 0,
            "away_score": game.final_away_score or 0,
            "trigger_type": "halftime",
            "trigger_status": trigger_status,
            "prediction_id": prediction_id,
        })

    return {
        "triggers": triggers,
        "count": len(triggers),
        "pending": len([t for t in triggers if t["trigger_status"] == "pending"]),
        "ready": len([t for t in triggers if t["trigger_status"] == "ready"]),
        "fired": len([t for t in triggers if t["trigger_status"] == "fired"]),
    }


@app.get("/api/predictions/performance", response_model=PerformanceMetrics)
def get_prediction_performance(
    days: int = Query(30, description="Number of days to include"),
    trigger_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get prediction performance metrics."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    query = db.query(Prediction).filter(Prediction.created_at >= cutoff)

    if trigger_type:
        query = query.filter(Prediction.trigger_type == trigger_type)

    predictions = query.all()

    total = len(predictions)
    correct = len([p for p in predictions if p.status == PredictionStatus.CORRECT])
    pending = len([p for p in predictions if p.status == PredictionStatus.PENDING])
    resolved = [p for p in predictions if p.status in (PredictionStatus.CORRECT, PredictionStatus.WRONG)]

    total_errors = [p.total_error for p in resolved if p.total_error is not None]
    margin_errors = [p.margin_error for p in resolved if p.margin_error is not None]

    return PerformanceMetrics(
        total_predictions=total,
        correct_predictions=correct,
        pending_predictions=pending,
        win_rate=(correct / len(resolved) * 100) if resolved else 0,
        total_mae=sum(total_errors) / len(total_errors) if total_errors else None,
        margin_mae=sum(margin_errors) / len(margin_errors) if margin_errors else None,
    )


# ============ Manual Prediction Endpoints ============

@app.post("/api/predictions/manual")
def create_manual_prediction(request: ManualPredictionRequest, db: Session = Depends(get_db)):
    """Create a manual prediction for a game."""
    try:
        from src.models.reptar_predictor import get_predictor
        from src.data.game_data import fetch_box, get_game_info, first_half_score, behavior_counts_1h, fetch_pbp_df

        predictor = get_predictor()

        # Fetch game data
        box = fetch_box(request.game_id)
        info = get_game_info(box)

        # Get or create game record
        game = db.query(Game).filter(Game.nba_id == request.game_id).first()
        if not game:
            game = Game(
                nba_id=request.game_id,
                game_date=datetime.utcnow(),
                home_team=info.get("home_tricode", "HOME"),
                away_team=info.get("away_tricode", "AWAY"),
                home_team_name=info.get("home_name"),
                away_team_name=info.get("away_name"),
            )
            db.add(game)
            db.commit()
            db.refresh(game)

        # Make prediction based on trigger type
        if request.trigger_type == "halftime":
            h1_home, h1_away = first_half_score(box)
            behavior = behavior_counts_1h(fetch_pbp_df(request.game_id))
            features, pred = predictor.predict(h1_home, h1_away, behavior)

            prediction = Prediction(
                game_id=game.id,
                trigger_type=TriggerType.HALFTIME,
                h1_home=h1_home,
                h1_away=h1_away,
                pred_total=pred["pred_final_total"],
                pred_margin=pred["pred_final_margin"],
                pred_home_score=pred["pred_final_home"],
                pred_away_score=pred["pred_final_away"],
                pred_winner=game.home_team if pred["pred_final_margin"] > 0 else game.away_team,
                home_win_prob=pred["home_win_prob"],
                total_q10=pred.get("total_q10"),
                total_q90=pred.get("total_q90"),
                margin_q10=pred.get("margin_q10"),
                margin_q90=pred.get("margin_q90"),
                status=PredictionStatus.PENDING,
                posted_to_discord=False,
            )
        else:
            raise HTTPException(status_code=400, detail=f"Trigger type {request.trigger_type} not yet supported")

        db.add(prediction)
        db.commit()
        db.refresh(prediction)

        return {"status": "success", "prediction_id": prediction.id, "prediction": pred}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/predictions/slate")
def create_slate_predictions(date: str = Query(..., description="Date for slate (YYYY-MM-DD)")):
    """Create pregame predictions for all games on a date."""
    try:
        from src.schedule import fetch_schedule
        from src.models.reptar_predictor import get_predictor

        schedule = fetch_schedule(date)
        games = schedule.get("games", [])

        results = []
        for game in games:
            nba_id = game.get("nba_id")
            if not nba_id:
                continue

            # For pregame, we'd need pregame model - skip for now
            results.append({
                "game_id": nba_id,
                "status": "skipped",
                "message": "Pregame predictions require pregame model"
            })

        return {"date": date, "results": results}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ Ghost Bettor Endpoints ============

@app.get("/api/ghost-bettor/config", response_model=GhostBettorConfigResponse)
def get_ghost_bettor_config(db: Session = Depends(get_db)):
    """Get ghost bettor configuration."""
    gb = GhostBettor(db)
    config = gb.get_config()
    return GhostBettorConfigResponse.model_validate(config)


@app.put("/api/ghost-bettor/config", response_model=GhostBettorConfigResponse)
def update_ghost_bettor_config(
    update: GhostBettorConfigUpdate,
    db: Session = Depends(get_db),
):
    """Update ghost bettor configuration."""
    gb = GhostBettor(db)
    config = gb.update_config(**update.model_dump(exclude_unset=True))
    return GhostBettorConfigResponse.model_validate(config)


@app.get("/api/ghost-bettor/stats", response_model=GhostBettorStats)
def get_ghost_bettor_stats(
    days: int = Query(30, description="Number of days to include"),
    db: Session = Depends(get_db),
):
    """Get ghost bettor performance statistics."""
    gb = GhostBettor(db)
    return gb.get_stats(days)


@app.get("/api/ghost-bettor/bets", response_model=List[GhostBetResponse])
def get_ghost_bets(
    status: Optional[str] = None,
    limit: int = Query(50, le=100),
    db: Session = Depends(get_db),
):
    """Get ghost bets."""
    query = db.query(GhostBet)

    if status:
        query = query.filter(GhostBet.result == status)

    return query.order_by(GhostBet.created_at.desc()).limit(limit).all()


@app.get("/api/ghost-bettor/pending", response_model=List[GhostBetResponse])
def get_pending_bets(db: Session = Depends(get_db)):
    """Get pending ghost bets."""
    gb = GhostBettor(db)
    return gb.get_pending_bets()


@app.get("/api/ghost-bettor/bankroll-history")
def get_bankroll_history(
    days: int = Query(30, description="Number of days to include"),
    db: Session = Depends(get_db),
):
    """Get bankroll history over time."""
    gb = GhostBettor(db)
    return gb.get_bankroll_history(days)


# ============ Live Data Endpoints ============

@app.get("/api/live/scores")
def get_live_scores(db: Session = Depends(get_db)):
    """Get live scores for today's games from database."""
    try:
        # Use UTC date and look for games in the last 24 hours to capture all today's games
        from datetime import date as date_type
        today = date_type.today()

        # Get games from today (using date portion of game_date)
        from sqlalchemy import func
        games = db.query(Game).filter(
            func.date(Game.game_date) == today
        ).order_by(Game.game_date).all()

        live_games = []
        seen_nba_ids = set()  # Deduplicate by nba_id

        for game in games:
            if game.nba_id in seen_nba_ids:
                continue  # Skip duplicates
            seen_nba_ids.add(game.nba_id)

            live_games.append({
                "game_id": game.nba_id,
                "db_id": game.id,
                "home": game.home_team_name or game.home_team,
                "away": game.away_team_name or game.away_team,
                "home_score": game.final_home_score or 0,
                "away_score": game.final_away_score or 0,
                "period": game.period or 0,
                "clock": game.clock or "",
                "status": game.game_status or "Scheduled",
            })

        return {"games": live_games, "date": str(today), "count": len(live_games)}

    except Exception as e:
        # Return empty games list on error instead of failing
        return {"games": [], "error": str(e)}


# ============ Schedule Endpoint ============

@app.get("/api/schedule/{date}")
def get_schedule(date: str):
    """Get NBA schedule for a specific date from NBA API."""
    try:
        from src.schedule import fetch_schedule

        schedule = fetch_schedule(date)
        games = schedule.get("games", [])

        return {
            "date": date,
            "games": [
                {
                    "nba_id": game.get("nba_id"),
                    "home_team": game.get("home_team"),
                    "away_team": game.get("away_team"),
                    "home_name": game.get("home_name"),
                    "away_name": game.get("away_name"),
                    "game_time": game.get("game_time"),
                }
                for game in games
                if game.get("nba_id")
            ]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ Health Check ============

@app.get("/api/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


# ============ Testing Endpoints ============

@app.get("/api/test/status")
def get_system_status(db: Session = Depends(get_db)):
    """Get comprehensive system status for testing."""
    from sqlalchemy import text

    status = {
        "timestamp": datetime.utcnow().isoformat(),
        "components": {},
        "overall": "healthy",
    }

    # Database check
    try:
        db.execute(text("SELECT 1"))
        status["components"]["database"] = {"status": "healthy", "message": "Connected"}
    except Exception as e:
        status["components"]["database"] = {"status": "error", "message": str(e)}
        status["overall"] = "degraded"

    # REPTAR model check
    try:
        from src.models.reptar_predictor import get_predictor
        predictor = get_predictor()
        # Check if model has the required attributes
        if predictor and hasattr(predictor, '_total_model') and predictor._total_model:
            status["components"]["reptar_model"] = {"status": "healthy", "message": "Model loaded"}
        elif predictor:
            status["components"]["reptar_model"] = {"status": "healthy", "message": "Predictor available"}
        else:
            status["components"]["reptar_model"] = {"status": "error", "message": "Model not loaded"}
            status["overall"] = "degraded"
    except Exception as e:
        status["components"]["reptar_model"] = {"status": "error", "message": str(e)}
        status["overall"] = "degraded"

    # Discord webhook check
    discord_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if discord_url:
        status["components"]["discord"] = {"status": "configured", "message": "Webhook URL set"}
    else:
        status["components"]["discord"] = {"status": "warning", "message": "No webhook URL configured"}

    # Ghost bettor config check
    try:
        config = db.query(GhostBettorConfig).first()
        if config:
            status["components"]["ghost_bettor"] = {
                "status": "healthy",
                "message": f"Active: {config.is_active}, Bankroll: ${config.current_bankroll}"
            }
        else:
            status["components"]["ghost_bettor"] = {"status": "warning", "message": "No config found"}
    except Exception as e:
        status["components"]["ghost_bettor"] = {"status": "error", "message": str(e)}

    # Pending predictions count
    try:
        pending_count = db.query(Prediction).filter(Prediction.status == PredictionStatus.PENDING).count()
        status["components"]["predictions"] = {"status": "healthy", "message": f"{pending_count} pending"}
    except Exception as e:
        status["components"]["predictions"] = {"status": "error", "message": str(e)}

    return status


class DiscordTestRequest(BaseModel):
    message: Optional[str] = "Test message from PerryPicks Dashboard"


@app.post("/api/test/discord")
def test_discord_connection(request: DiscordTestRequest = DiscordTestRequest()):
    """Test Discord webhook connection by sending a test message."""
    import requests

    discord_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not discord_url:
        raise HTTPException(status_code=400, detail="DISCORD_WEBHOOK_URL not configured")

    try:
        payload = {
            "content": f"🧪 **Test Message**\n{request.message}\n\n_Timestamp: {datetime.utcnow().isoformat()}_",
            "username": "PerryPicks Test",
        }
        response = requests.post(discord_url, json=payload, timeout=10)

        if response.status_code == 204 or response.status_code == 200:
            return {"success": True, "message": "Discord message sent successfully"}
        else:
            return {"success": False, "message": f"Discord returned status {response.status_code}", "response": response.text}

    except requests.Timeout:
        raise HTTPException(status_code=504, detail="Discord request timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class FakeTriggerRequest(BaseModel):
    delay_seconds: int = 30
    post_to_discord: bool = True


# In-memory storage for fake triggers (for testing)
_fake_triggers = {}


@app.post("/api/test/fake-trigger")
def queue_fake_trigger(request: FakeTriggerRequest):
    """Queue a fake trigger that will fire after specified delay."""
    import uuid
    import threading

    trigger_id = str(uuid.uuid4())[:8]

    def execute_fake_trigger():
        import time
        time.sleep(request.delay_seconds)

        # Generate fake prediction
        fake_prediction = {
            "away_team": "TEST",
            "home_team": "FAKE",
            "h1_away": 55,
            "h1_home": 52,
            "pred_total": 224.5,
            "pred_margin": 3.5,
            "home_win_prob": 0.62,
            "total_q10": 210,
            "total_q90": 239,
        }

        # Post to Discord if enabled
        if request.post_to_discord:
            discord_url = os.environ.get("DISCORD_WEBHOOK_URL")
            if discord_url:
                import requests
                content = f"""🧪 **FAKE TRIGGER TEST**

**TEST @ FAKE**
Half: 55 - 52

**Projected Final**
Total: {fake_prediction['pred_total']:.1f}
Margin: {fake_prediction['pred_margin']:+.1f}
Win Prob: {fake_prediction['home_win_prob']:.1%} FAKE

80% CI: {fake_prediction['total_q10']:.0f} - {fake_prediction['total_q90']:.0f}

⚠️ *This is a TEST trigger - no odds were fetched*
_Trigger ID: {trigger_id}_"""
                try:
                    requests.post(discord_url, json={"content": content, "username": "PerryPicks Test"}, timeout=10)
                except:
                    pass

        # Update trigger status
        _fake_triggers[trigger_id]["status"] = "completed"
        _fake_triggers[trigger_id]["completed_at"] = datetime.utcnow().isoformat()

    # Store trigger info
    _fake_triggers[trigger_id] = {
        "id": trigger_id,
        "status": "pending",
        "delay_seconds": request.delay_seconds,
        "post_to_discord": request.post_to_discord,
        "created_at": datetime.utcnow().isoformat(),
    }

    # Start background thread
    thread = threading.Thread(target=execute_fake_trigger, daemon=True)
    thread.start()

    return {
        "success": True,
        "trigger_id": trigger_id,
        "message": f"Fake trigger queued - will fire in {request.delay_seconds} seconds",
        "post_to_discord": request.post_to_discord,
    }


@app.get("/api/test/fake-trigger/{trigger_id}")
def get_fake_trigger_status(trigger_id: str):
    """Get status of a fake trigger."""
    if trigger_id not in _fake_triggers:
        raise HTTPException(status_code=404, detail="Trigger not found")
    return _fake_triggers[trigger_id]


@app.get("/api/test/fake-triggers")
def list_fake_triggers():
    """List all fake triggers."""
    return {"triggers": list(_fake_triggers.values())}


@app.delete("/api/test/fake-triggers")
def clear_fake_triggers():
    """Clear completed fake triggers."""
    global _fake_triggers
    completed = [k for k, v in _fake_triggers.items() if v["status"] == "completed"]
    for k in completed:
        del _fake_triggers[k]
    return {"cleared": len(completed)}


@app.post("/api/test/prediction")
def test_prediction():
    """Test prediction generation with sample data."""
    try:
        from src.models.reptar_predictor import get_predictor

        predictor = get_predictor()
        if not predictor:
            raise HTTPException(status_code=500, detail="Predictor not loaded")

        # Use sample halftime scores
        h1_home, h1_away = 58, 55
        behavior = {
            "fga_home": 45, "fga_away": 42,
            "fg3a_home": 15, "fg3a_away": 18,
            "fta_home": 12, "fta_away": 10,
            "oreb_home": 6, "oreb_away": 5,
            "dreb_home": 18, "dreb_away": 20,
            "ast_home": 14, "ast_away": 12,
            "tov_home": 8, "tov_away": 10,
            "stl_home": 5, "stl_away": 4,
            "blk_home": 3, "blk_away": 2,
            "pf_home": 10, "pf_away": 12,
        }

        features, pred = predictor.predict(h1_home, h1_away, behavior)

        return {
            "success": True,
            "input": {"h1_home": h1_home, "h1_away": h1_away},
            "prediction": {
                "pred_final_total": pred["pred_final_total"],
                "pred_final_margin": pred["pred_final_margin"],
                "home_win_prob": pred.get("home_win_prob"),
                "total_q10": pred.get("total_q10"),
                "total_q90": pred.get("total_q90"),
            },
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/test/database")
def test_database_write(db: Session = Depends(get_db)):
    """Test database write capability."""
    try:
        # Create a test prediction and immediately delete it
        from database import Game

        test_game = Game(
            nba_id="TEST_" + str(uuid.uuid4())[:8],
            game_date=datetime.utcnow(),
            home_team="TEST",
            away_team="TEST",
            home_team_name="Test Team",
            away_team_name="Test Team",
        )
        db.add(test_game)
        db.commit()
        db.refresh(test_game)

        # Delete it
        db.delete(test_game)
        db.commit()

        return {"success": True, "message": "Database write test passed"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/test/odds-status")
def odds_api_status():
    """Check if Odds API is configured (without making a call)."""
    api_key = os.environ.get("ODDS_API_KEY")
    if api_key:
        return {
            "configured": True,
            "message": "Odds API key is set",
            "key_preview": api_key[:8] + "..." if len(api_key) > 8 else "***"
        }
    return {"configured": False, "message": "ODDS_API_KEY not set"}


# ============ Game Detail Endpoints ============

@app.get("/api/games/{game_id}/details")
def get_game_details(game_id: int, db: Session = Depends(get_db)):
    """Get detailed information about a game including all predictions."""
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    # Get all predictions for this game
    predictions = db.query(Prediction).filter(Prediction.game_id == game_id).all()

    # Get all betting recommendations for this game
    recommendations = []
    for pred in predictions:
        recs = db.query(BettingRecommendation).filter(BettingRecommendation.prediction_id == pred.id).all()
        for rec in recs:
            recommendations.append({
                "id": rec.id,
                "prediction_id": pred.id,
                "trigger_type": pred.trigger_type,
                "bet_type": rec.bet_type,
                "pick": rec.pick,
                "line": rec.line,
                "odds": rec.odds,
                "edge": rec.edge,
                "probability": rec.probability,
                "confidence_tier": rec.confidence_tier,
            })

    # Get ghost bets for this game
    ghost_bets = db.query(GhostBet).filter(GhostBet.game_id == game_id).all()

    return {
        "game": {
            "id": game.id,
            "nba_id": game.nba_id,
            "game_date": game.game_date.isoformat() if game.game_date else None,
            "home_team": game.home_team,
            "away_team": game.away_team,
            "home_team_name": game.home_team_name,
            "away_team_name": game.away_team_name,
            "final_home_score": game.final_home_score,
            "final_away_score": game.final_away_score,
            "final_total": game.final_total,
            "final_margin": game.final_margin,
            "game_status": game.game_status,
        },
        "predictions": [
            {
                "id": p.id,
                "trigger_type": p.trigger_type,
                "h1_home": p.h1_home,
                "h1_away": p.h1_away,
                "pred_total": p.pred_total,
                "pred_margin": p.pred_margin,
                "pred_home_score": p.pred_home_score,
                "pred_away_score": p.pred_away_score,
                "pred_winner": p.pred_winner,
                "home_win_prob": p.home_win_prob,
                "total_q10": p.total_q10,
                "total_q90": p.total_q90,
                "margin_q10": p.margin_q10,
                "margin_q90": p.margin_q90,
                "status": p.status,
                "actual_total": p.actual_total,
                "actual_margin": p.actual_margin,
                "actual_winner": p.actual_winner,
                "total_error": p.total_error,
                "margin_error": p.margin_error,
                "winner_correct": p.winner_correct,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in predictions
        ],
        "recommendations": recommendations,
        "ghost_bets": [
            {
                "id": b.id,
                "bet_type": b.bet_type,
                "pick": b.pick,
                "line": b.line,
                "odds": b.odds,
                "edge": b.edge,
                "probability": b.probability,
                "confidence_tier": b.confidence_tier,
                "bet_amount": b.bet_amount,
                "potential_payout": b.potential_payout,
                "result": b.result,
                "actual_payout": b.actual_payout,
            }
            for b in ghost_bets
        ],
    }


# ============ System Config Endpoints ============

class SystemConfigResponse(BaseModel):
    pregame_enabled: bool
    halftime_enabled: bool
    q3_5min_enabled: bool
    odds_fetch_enabled: bool

    class Config:
        from_attributes = True


class SystemConfigUpdate(BaseModel):
    pregame_enabled: Optional[bool] = None
    halftime_enabled: Optional[bool] = None
    q3_5min_enabled: Optional[bool] = None
    odds_fetch_enabled: Optional[bool] = None


@app.get("/api/system/config")
def get_system_config(db: Session = Depends(get_db)):
    """Get current system configuration."""
    config = db.query(SystemConfig).first()
    if not config:
        config = SystemConfig()
        db.add(config)
        db.commit()
        db.refresh(config)

    return {
        "pregame_enabled": config.pregame_enabled,
        "halftime_enabled": config.halftime_enabled,
        "q3_5min_enabled": config.q3_5min_enabled,
        "odds_fetch_enabled": config.odds_fetch_enabled,
    }


@app.put("/api/system/config")
def update_system_config(update: SystemConfigUpdate, db: Session = Depends(get_db)):
    """Update system configuration."""
    config = db.query(SystemConfig).first()
    if not config:
        config = SystemConfig()
        db.add(config)

    if update.pregame_enabled is not None:
        config.pregame_enabled = update.pregame_enabled
    if update.halftime_enabled is not None:
        config.halftime_enabled = update.halftime_enabled
    if update.q3_5min_enabled is not None:
        config.q3_5min_enabled = update.q3_5min_enabled
    if update.odds_fetch_enabled is not None:
        config.odds_fetch_enabled = update.odds_fetch_enabled

    db.commit()
    db.refresh(config)

    return {
        "pregame_enabled": config.pregame_enabled,
        "halftime_enabled": config.halftime_enabled,
        "q3_5min_enabled": config.q3_5min_enabled,
        "odds_fetch_enabled": config.odds_fetch_enabled,
    }


# ============ Daily Summary Endpoints ============

@app.get("/api/summary/daily")
def get_daily_summary(date: Optional[str] = None, db: Session = Depends(get_db)):
    """Get daily summary for a specific date (defaults to today).

    Tracks predictions by:
    - Trigger type: pregame, halftime, q3_5min
    - Bet type: total (over/under), spread, moneyline

    A "correct" prediction is determined by:
    - Total: model predicted over/under correctly vs actual total
    - Spread: model predicted cover/not cover correctly
    - Moneyline: model predicted winner correctly (winner_correct field)
    """
    if date:
        target_date = datetime.strptime(date, "%Y-%m-%d")
    else:
        target_date = datetime.utcnow()

    date_start = datetime(target_date.year, target_date.month, target_date.day)
    date_end = date_start + timedelta(days=1)

    # Get games for the day
    games = db.query(Game).filter(
        Game.game_date >= date_start,
        Game.game_date < date_end
    ).all()

    # Get predictions for the day
    predictions = db.query(Prediction).filter(
        Prediction.created_at >= date_start,
        Prediction.created_at < date_end
    ).all()

    # Get betting recommendations for the day (via prediction IDs)
    prediction_ids = [p.id for p in predictions]
    recommendations = db.query(BettingRecommendation).filter(
        BettingRecommendation.prediction_id.in_(prediction_ids)
    ).all() if prediction_ids else []

    # Get ghost bets for the day
    ghost_bets = db.query(GhostBet).filter(
        GhostBet.created_at >= date_start,
        GhostBet.created_at < date_end
    ).all()

    # Calculate metrics
    games_monitored = len(games)
    games_final = len([g for g in games if g.game_status == "Final"])

    # Winner predictions (from Prediction table)
    winner_correct = len([p for p in predictions if p.winner_correct is True])
    winner_wrong = len([p for p in predictions if p.winner_correct is False])
    winner_pending = len([p for p in predictions if p.winner_correct is None])

    # Bet type breakdown (from BettingRecommendation table)
    def count_by_bet_type(bet_type_enum):
        # Handle both enum and string values for compatibility
        type_recs = [r for r in recommendations if r.bet_type == bet_type_enum or r.bet_type == bet_type_enum.value]
        return {
            "total": len(type_recs),
            "won": len([r for r in type_recs if r.result == BetStatus.WON or r.result == "won"]),
            "lost": len([r for r in type_recs if r.result == BetStatus.LOST or r.result == "lost"]),
            "pending": len([r for r in type_recs if r.result == BetStatus.PENDING or r.result == "pending"]),
            "push": len([r for r in type_recs if r.result == BetStatus.PUSH or r.result == "push"]),
            "win_rate": 0.0
        }

    totals = count_by_bet_type(BetType.TOTAL)
    spreads = count_by_bet_type(BetType.SPREAD)
    moneylines = count_by_bet_type(BetType.MONEYLINE)

    # Calculate win rates
    for bet_stats in [totals, spreads, moneylines]:
        resolved = bet_stats["won"] + bet_stats["lost"]
        bet_stats["win_rate"] = (bet_stats["won"] / resolved * 100) if resolved > 0 else 0

    # Ghost bettor stats
    bets_won = len([b for b in ghost_bets if b.result == BetStatus.WON or b.result == "won"])
    bets_lost = len([b for b in ghost_bets if b.result == BetStatus.LOST or b.result == "lost"])
    bets_pending = len([b for b in ghost_bets if b.result == BetStatus.PENDING or b.result == "pending"])
    total_wagered = sum(b.bet_amount for b in ghost_bets if b.result not in [BetStatus.PENDING, "pending"])
    total_return = sum(b.actual_payout or 0 for b in ghost_bets if b.result not in [BetStatus.PENDING, "pending"])
    profit_loss = total_return - total_wagered

    # Calculate MAE for resolved predictions
    total_errors = [p.total_error for p in predictions if p.total_error is not None]
    margin_errors = [p.margin_error for p in predictions if p.margin_error is not None]

    return {
        "date": date_start.strftime("%Y-%m-%d"),
        "games": {
            "monitored": games_monitored,
            "final": games_final,
            "in_progress": games_monitored - games_final,
        },
        "predictions": {
            "total": len(predictions),
            "winner_correct": winner_correct,
            "winner_wrong": winner_wrong,
            "winner_pending": winner_pending,
            "winner_accuracy": (winner_correct / (winner_correct + winner_wrong) * 100) if (winner_correct + winner_wrong) > 0 else 0,
            "total_mae": sum(total_errors) / len(total_errors) if total_errors else None,
            "margin_mae": sum(margin_errors) / len(margin_errors) if margin_errors else None,
        },
        "by_bet_type": {
            "total": totals,
            "spread": spreads,
            "moneyline": moneylines,
        },
        "ghost_bets": {
            "total": len(ghost_bets),
            "won": bets_won,
            "lost": bets_lost,
            "pending": bets_pending,
            "win_rate": (bets_won / (bets_won + bets_lost) * 100) if (bets_won + bets_lost) > 0 else 0,
            "total_wagered": total_wagered,
            "total_return": total_return,
            "profit_loss": profit_loss,
        },
        "by_trigger_type": {
            "halftime": {
                "total": len([p for p in predictions if p.trigger_type == TriggerType.HALFTIME or p.trigger_type == "halftime"]),
                "winner_correct": len([p for p in predictions if (p.trigger_type == TriggerType.HALFTIME or p.trigger_type == "halftime") and p.winner_correct is True]),
            },
            "q3_5min": {
                "total": len([p for p in predictions if p.trigger_type == TriggerType.Q3_5MIN or p.trigger_type == "q3_5min"]),
                "winner_correct": len([p for p in predictions if (p.trigger_type == TriggerType.Q3_5MIN or p.trigger_type == "q3_5min") and p.winner_correct is True]),
            },
            "pregame": {
                "total": len([p for p in predictions if p.trigger_type == TriggerType.PREGAME or p.trigger_type == "pregame"]),
                "winner_correct": len([p for p in predictions if (p.trigger_type == TriggerType.PREGAME or p.trigger_type == "pregame") and p.winner_correct is True]),
            },
        },
    }


# ============ Trigger Timeline Endpoints ============

@app.get("/api/timeline/today")
def get_todays_timeline(db: Session = Depends(get_db)):
    """Get today's games with trigger status for timeline view."""
    from src.schedule import fetch_schedule
    from datetime import date as date_type

    # Use local date (games are scheduled in Eastern time)
    today = date_type.today()
    today_str = today.strftime("%Y-%m-%d")
    date_start = datetime(today.year, today.month, today.day)
    date_end = date_start + timedelta(days=1)

    # Get games from database
    db_games = db.query(Game).filter(
        Game.game_date >= date_start,
        Game.game_date < date_end
    ).all()

    # Get predictions to determine trigger status
    game_ids = [g.id for g in db_games]
    predictions = db.query(Prediction).filter(Prediction.game_id.in_(game_ids)).all() if game_ids else []

    # Build trigger status map
    trigger_status = {}
    for pred in predictions:
        key = f"{pred.game_id}:{pred.trigger_type}"
        trigger_status[key] = pred.status

    # Try to get schedule for game times
    games_list = []
    seen_nba_ids = set()  # Track seen games to prevent duplicates

    try:
        schedule = fetch_schedule(today)
        for game in schedule.get("games", []):
            nba_id = game.get("nba_id")
            if not nba_id or nba_id in seen_nba_ids:
                continue  # Skip duplicates

            seen_nba_ids.add(nba_id)

            # Find matching db game
            db_game = next((g for g in db_games if g.nba_id == nba_id), None)

            game_id = db_game.id if db_game else None

            games_list.append({
                "game_id": game_id,
                "nba_id": nba_id,
                "home_team": game.get("home_team"),
                "away_team": game.get("away_team"),
                "home_name": game.get("home_name"),
                "away_name": game.get("away_name"),
                "game_time": game.get("game_time"),
                "game_status": db_game.game_status if db_game else "Scheduled",
                "home_score": db_game.final_home_score if db_game else None,
                "away_score": db_game.final_away_score if db_game else None,
                "triggers": {
                    "pregame": {
                        "status": trigger_status.get(f"{game_id}:pregame", "pending"),
                    },
                    "halftime": {
                        "status": trigger_status.get(f"{game_id}:halftime", "pending"),
                    },
                    "q3_5min": {
                        "status": trigger_status.get(f"{game_id}:q3_5min", "pending"),
                    },
                },
            })
    except Exception as e:
        # Fallback to db games only
        for game in db_games:
            if game.nba_id in seen_nba_ids:
                continue  # Skip duplicates
            seen_nba_ids.add(game.nba_id)

            games_list.append({
                "game_id": game.id,
                "nba_id": game.nba_id,
                "home_team": game.home_team,
                "away_team": game.away_team,
                "home_name": game.home_team_name,
                "away_name": game.away_team_name,
                "game_time": None,
                "game_status": game.game_status,
                "home_score": game.final_home_score,
                "away_score": game.final_away_score,
                "triggers": {
                    "pregame": {"status": trigger_status.get(f"{game.id}:pregame", "pending")},
                    "halftime": {"status": trigger_status.get(f"{game.id}:halftime", "pending")},
                    "q3_5min": {"status": trigger_status.get(f"{game.id}:q3_5min", "pending")},
                },
            })

    return {
        "date": today_str,
        "games": games_list,
        "total_games": len(games_list),
        "triggers_pending": sum(1 for g in games_list for t in g["triggers"].values() if t["status"] == "pending"),
        "triggers_fired": sum(1 for g in games_list for t in g["triggers"].values() if t["status"] != "pending"),
    }


# ============================================================================
# ADMIN ENDPOINTS - Remote Remediation & Alerts
# ============================================================================

@app.get("/admin/alerts")
async def get_recent_alerts(count: int = Query(20, ge=1, le=100)):
    """Get recent alerts from the alert system."""
    try:
        from src.automation.remediation import get_alert_manager
        alert_manager = get_alert_manager()
        alerts = alert_manager.get_recent_alerts(count)

        return {
            "alerts": [
                {
                    "level": a.level.value,
                    "title": a.title,
                    "message": a.message,
                    "timestamp": a.timestamp.isoformat(),
                    "remedy_available": a.remedy_available,
                    "remedy_action": a.remedy_action,
                }
                for a in alerts
            ],
            "total": len(alerts),
        }
    except Exception as e:
        return {"alerts": [], "error": str(e)}


@app.get("/admin/remedies")
async def list_remedies():
    """List available remediation actions."""
    try:
        from src.automation.remediation import get_remediation_manager
        remedy_manager = get_remediation_manager()
        return {
            "actions": remedy_manager.list_actions(),
            "description": {
                "refresh_temporal_data": "Reload temporal feature store with recent games",
                "clear_cache": "Clear NBA CDN cache directory",
                "reload_model": "Force reload REPTAR model",
                "restart_odds_api": "Restart the local Odds API server",
                "run_data_backfill": "Backfill missing historical data",
                "health_check": "Run comprehensive system health check",
                "get_status": "Get current system status",
            },
        }
    except Exception as e:
        return {"actions": [], "error": str(e)}


@app.post("/admin/remedy/{action_name}")
async def execute_remedy(action_name: str, background_tasks: BackgroundTasks):
    """
    Execute a remediation action.

    This endpoint can be called remotely (from phone, etc.) to trigger fixes.
    """
    try:
        from src.automation.remediation import get_remediation_manager
        remedy_manager = get_remediation_manager()

        # Execute in background for long-running actions
        result = remedy_manager.execute(action_name)

        return {
            "action": action_name,
            "success": result.get("success", False),
            "message": result.get("message", ""),
            "details": result,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        return {
            "action": action_name,
            "success": False,
            "message": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }


@app.get("/admin/health")
async def admin_health_check():
    """Run comprehensive health check."""
    try:
        from src.automation.remediation import get_remediation_manager
        remedy_manager = get_remediation_manager()
        result = remedy_manager.execute("health_check")

        return {
            **result,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        return {
            "success": False,
            "message": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }


# ============================================================================
# LIVE BET TRACKING - Probability tracking for active bets
# ============================================================================

def send_live_tracking_alert(
    game: Game,
    rec: BettingRecommendation,
    pred: Prediction,
    live_probability: float,
    alert_type: str,
    current_scores: dict,
    period: int,
    clock: str,
    previous_probability: float = None,
) -> bool:
    """
    Send Discord alert for live tracking threshold crossing.

    Alert types:
    - high_confidence: probability >= 80%
    - cashout: probability <= 20%

    Posting rules:
    - High confidence: Post at 80%, then only if probability increased by 5%+ since last post
    - Cashout: Only post once per bet
    """
    import requests

    # Use dedicated live tracking webhook, fall back to main
    discord_url = os.environ.get("DISCORD_LIVE_TRACKING_WEBHOOK") or os.environ.get("DISCORD_WEBHOOK_URL")
    if not discord_url:
        return False

    bet_type_str = rec.bet_type.value if hasattr(rec.bet_type, 'value') else str(rec.bet_type)
    pick_str = rec.pick.upper()

    if alert_type == "high_confidence":
        emoji = "🎯"
        color_text = "HIGH CONFIDENCE"
        description = f"Bet is **{(live_probability * 100):.0f}%** likely to hit!"

        # Add probability increase indicator if this is an update
        if previous_probability and previous_probability >= 0.80:
            increase = (live_probability - previous_probability) * 100
            description += f"\n📈 Probability up **{increase:.0f}%** since last update!"
    else:  # cashout
        emoji = "💰"
        color_text = "CASHOUT RECOMMENDED"
        description = f"Probability dropped to **{(live_probability * 100):.0f}%** - consider cashing out"

    content = f"""{emoji} **{color_text}**

**{game.away_team_name or game.away_team} @ {game.home_team_name or game.home_team}**
Q{period} {clock} | Score: {current_scores['away']} - {current_scores['home']}

**Bet:** {pick_str} {bet_type_str.upper()} {rec.line}
**Initial Prob:** {(rec.probability or 0) * 100:.0f}%
**Live Prob:** {live_probability * 100:.0f}%

{description}

_Model prediction: Total {pred.pred_total:.1f}, Margin {pred.pred_margin:+.1f}_
_Tracked by PerryPicks Live_"""

    try:
        response = requests.post(
            discord_url,
            json={
                "content": content,
                "username": "PerryPicks Live Tracker",
            },
            timeout=10
        )
        return response.status_code in (200, 204)
    except Exception as e:
        logger.error(f"Failed to send live tracking alert: {e}")
        return False


def calculate_live_probability(
    bet_type: str,
    bet_pick: str,
    bet_line: float,
    pred_total: float,
    pred_margin: float,
    current_home_score: int,
    current_away_score: int,
    period: int,
    clock: str,
) -> dict:
    """
    Calculate live probability of a bet hitting based on current game state.

    Returns dict with:
    - live_probability: 0-1 probability bet hits
    - points_needed: points still needed
    - time_remaining: seconds left
    - scoring_rate: expected points per minute
    """
    current_total = current_home_score + current_away_score
    current_margin = current_home_score - current_away_score

    # Parse clock to seconds (format: "M:SS")
    try:
        parts = clock.split(":")
        minutes = int(parts[0])
        seconds = int(parts[1])
        clock_seconds = minutes * 60 + seconds
    except:
        clock_seconds = 0

    # Calculate total seconds remaining (including OT periods)
    periods_remaining = max(0, 4 - period) if period <= 4 else 0
    time_remaining = clock_seconds + (periods_remaining * 720)  # 12 min per quarter

    if period > 4:
        # OT - just use current clock
        time_remaining = clock_seconds

    # Average NBA scoring rate: ~2.1 points per minute per team = ~4.2 total
    # Adjust based on game flow
    if period <= 2:
        scoring_rate = 4.0  # First half pace
    elif period == 3:
        scoring_rate = 4.2  # Typical pace
    else:
        scoring_rate = 4.5  # 4th quarter tends to be faster due to fouls/FTs

    # Expected points remaining
    expected_points_remaining = (time_remaining / 60) * scoring_rate

    # Calculate probability based on bet type
    if bet_type == "total" or bet_type.lower() == "total":
        # Total bet (OVER/UNDER)
        if bet_pick.upper() == "OVER":
            points_needed = bet_line - current_total
            if points_needed <= 0:
                probability = 1.0  # Already hit
            elif time_remaining <= 0:
                probability = 0.0  # No time left
            else:
                # Probability based on expected scoring
                margin_for_error = expected_points_remaining - points_needed
                # Use normal distribution approximation
                # Standard deviation of final score ~8-10 points at halftime, decreases over time
                remaining_uncertainty = scoring_rate * (time_remaining / 60) ** 0.5 * 2.5
                if remaining_uncertainty > 0:
                    z_score = margin_for_error / remaining_uncertainty
                    # Simplified normal CDF
                    probability = 0.5 * (1 + (2 / 3.14159) ** 0.5 * z_score / (1 + 0.2315 * abs(z_score)))
                    probability = max(0.01, min(0.99, probability))
                else:
                    probability = 0.5 if points_needed <= expected_points_remaining else 0.0
        else:  # UNDER
            points_needed = current_total - bet_line
            if points_needed >= 0:
                probability = 0.0  # Already lost (over the line)
            elif time_remaining <= 0:
                probability = 1.0  # Won
            else:
                margin_for_error = -points_needed - expected_points_remaining
                remaining_uncertainty = scoring_rate * (time_remaining / 60) ** 0.5 * 2.5
                if remaining_uncertainty > 0:
                    z_score = margin_for_error / remaining_uncertainty
                    probability = 0.5 * (1 + (2 / 3.14159) ** 0.5 * z_score / (1 + 0.2315 * abs(z_score)))
                    probability = max(0.01, min(0.99, probability))
                else:
                    probability = 0.5 if -points_needed >= expected_points_remaining else 1.0

    elif bet_type == "spread" or bet_type.lower() == "spread":
        # Spread bet
        if bet_pick.upper() == "HOME":
            # Home needs to win by more than line (or lose by less if line is negative)
            margin_needed = bet_line + current_margin  # If line is -3.5 and home up by 5, need to stay > 3.5 ahead
            # Actually: we bet home -3.5, so home needs to win by 4+
            # Current margin is home - away
            # Bet wins if: final_margin > bet_line (if betting home)
            margin_vs_line = current_margin - bet_line
            if margin_vs_line > 0:
                # Currently covering
                remaining_uncertainty = scoring_rate * (time_remaining / 60) ** 0.5 * 1.5
                probability = 0.5 + 0.5 * (1 - (remaining_uncertainty / (remaining_uncertainty + abs(margin_vs_line))))
            else:
                # Not covering, need to make up ground
                remaining_uncertainty = scoring_rate * (time_remaining / 60) ** 0.5 * 1.5
                probability = 0.5 * (abs(margin_vs_line) / (remaining_uncertainty + abs(margin_vs_line)))
        else:  # AWAY
            margin_vs_line = -current_margin - bet_line  # Away perspective
            if margin_vs_line > 0:
                remaining_uncertainty = scoring_rate * (time_remaining / 60) ** 0.5 * 1.5
                probability = 0.5 + 0.5 * (1 - (remaining_uncertainty / (remaining_uncertainty + abs(margin_vs_line))))
            else:
                remaining_uncertainty = scoring_rate * (time_remaining / 60) ** 0.5 * 1.5
                probability = 0.5 * (abs(margin_vs_line) / (remaining_uncertainty + abs(margin_vs_line)))
        points_needed = margin_vs_line
        probability = max(0.01, min(0.99, probability))

    else:  # Moneyline
        # Binary win/loss
        if bet_pick.upper() == "HOME":
            if current_margin > 10 and time_remaining < 120:
                probability = 0.95
            elif current_margin > 5 and time_remaining < 60:
                probability = 0.90
            elif current_margin < -10 and time_remaining < 120:
                probability = 0.05
            elif current_margin < -5 and time_remaining < 60:
                probability = 0.10
            else:
                # Use model's home_win_prob adjusted for current state
                margin_factor = current_margin / 20  # Normalize
                time_factor = time_remaining / 2880  # Normalize to full game
                probability = 0.5 + margin_factor * (1 - time_factor * 0.5)
        else:  # AWAY
            if current_margin < -10 and time_remaining < 120:
                probability = 0.95
            elif current_margin < -5 and time_remaining < 60:
                probability = 0.90
            elif current_margin > 10 and time_remaining < 120:
                probability = 0.05
            elif current_margin > 5 and time_remaining < 60:
                probability = 0.10
            else:
                margin_factor = -current_margin / 20
                time_factor = time_remaining / 2880
                probability = 0.5 + margin_factor * (1 - time_factor * 0.5)
        points_needed = current_margin if bet_pick.upper() == "HOME" else -current_margin
        probability = max(0.01, min(0.99, probability))

    return {
        "live_probability": round(probability, 4),
        "points_needed": round(points_needed, 2) if 'points_needed' in dir() else 0,
        "time_remaining": time_remaining,
        "scoring_rate": scoring_rate,
        "expected_final_total": round(current_total + expected_points_remaining, 1),
        "current_total": current_total,
        "current_margin": current_margin,
    }


@app.get("/api/live-tracking/recommendations/{game_id}")
def get_live_tracking_for_game(game_id: int, db: Session = Depends(get_db)):
    """Get live tracking status for all recommendations of a game."""
    # Get the game
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    # Get predictions for this game
    predictions = db.query(Prediction).filter(Prediction.game_id == game_id).all()

    results = []
    for pred in predictions:
        # Get recommendations for this prediction
        # Use raw query to avoid enum case sensitivity issues
        from sqlalchemy import text
        recs_data = db.execute(
            text("SELECT * FROM betting_recommendations WHERE prediction_id = :pred_id"),
            {"pred_id": pred.id}
        ).fetchall()

        for rec_data in recs_data:
            # Convert row to dict
            rec_dict = dict(rec_data._mapping) if hasattr(rec_data, '_mapping') else dict(rec_data)

            # Get existing snapshots
            snapshots = db.query(LiveBetSnapshot).filter(
                LiveBetSnapshot.recommendation_id == rec_dict['id']
            ).order_by(LiveBetSnapshot.created_at).all()

            # Calculate current live probability if game is in progress
            current_prob = None
            if game.period and game.period > 0 and game.game_status != "Final":
                bet_type_str = str(rec_dict['bet_type']).lower()
                calc = calculate_live_probability(
                    bet_type=bet_type_str,
                    bet_pick=rec_dict['pick'],
                    bet_line=rec_dict['line'],
                    pred_total=pred.pred_total,
                    pred_margin=pred.pred_margin,
                    current_home_score=game.final_home_score or 0,
                    current_away_score=game.final_away_score or 0,
                    period=game.period,
                    clock=game.clock or "0:00",
                )
                current_prob = calc

            results.append({
                "recommendation_id": rec_dict['id'],
                "prediction_id": pred.id,
                "bet_type": str(rec_dict['bet_type']),
                "pick": rec_dict['pick'],
                "line": rec_dict['line'],
                "odds": rec_dict['odds'],
                "initial_probability": rec_dict['probability'],
                "current_probability": current_prob,
                "snapshots": [
                    {
                        "id": s.id,
                        "period": s.period,
                        "clock": s.clock,
                        "home_score": s.home_score,
                        "away_score": s.away_score,
                        "live_probability": s.live_probability,
                        "alert_sent": s.alert_sent,
                        "alert_type": s.alert_type,
                        "created_at": s.created_at.isoformat(),
                    }
                    for s in snapshots
                ],
                "result": str(rec_dict['result']),
            })

    return {
        "game_id": game_id,
        "home_team": game.home_team,
        "away_team": game.away_team,
        "game_status": game.game_status,
        "period": game.period,
        "clock": game.clock,
        "home_score": game.final_home_score,
        "away_score": game.final_away_score,
        "recommendations": results,
    }


@app.post("/api/live-tracking/snapshot/{recommendation_id}")
def create_live_snapshot(
    recommendation_id: int,
    db: Session = Depends(get_db)
):
    """
    Create a live probability snapshot for a recommendation.
    Called periodically during game by automation.
    """
    rec = db.query(BettingRecommendation).filter(
        BettingRecommendation.id == recommendation_id
    ).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found")

    pred = db.query(Prediction).filter(Prediction.id == rec.prediction_id).first()
    game = db.query(Game).filter(Game.id == pred.game_id).first()

    if not game or game.game_status == "Final":
        return {"status": "game_ended", "message": "Game is over"}

    # Calculate live probability
    calc = calculate_live_probability(
        bet_type=rec.bet_type.value if hasattr(rec.bet_type, 'value') else str(rec.bet_type),
        bet_pick=rec.pick,
        bet_line=rec.line,
        pred_total=pred.pred_total,
        pred_margin=pred.pred_margin,
        current_home_score=game.final_home_score or 0,
        current_away_score=game.final_away_score or 0,
        period=game.period,
        clock=game.clock or "0:00",
    )

    # Create snapshot
    snapshot = LiveBetSnapshot(
        recommendation_id=recommendation_id,
        prediction_id=pred.id,
        game_id=game.id,
        period=game.period,
        clock=game.clock,
        home_score=game.final_home_score or 0,
        away_score=game.final_away_score or 0,
        game_seconds_remaining=calc["time_remaining"],
        pred_total=pred.pred_total,
        pred_margin=pred.pred_margin,
        bet_type=rec.bet_type.value if hasattr(rec.bet_type, 'value') else str(rec.bet_type),
        bet_pick=rec.pick,
        bet_line=rec.line,
        points_needed=calc["points_needed"],
        time_remaining=calc["time_remaining"],
        scoring_rate=calc["scoring_rate"],
        live_probability=calc["live_probability"],
    )

    # Check for alert thresholds
    alert_type = None
    if calc["live_probability"] >= 0.80:
        alert_type = "high_confidence"
    elif calc["live_probability"] <= 0.20:
        alert_type = "cashout"

    # Get last snapshot to check posting rules
    last_snapshot = db.query(LiveBetSnapshot).filter(
        LiveBetSnapshot.recommendation_id == recommendation_id
    ).order_by(LiveBetSnapshot.created_at.desc()).first()

    # Get last POSTED snapshot (for high confidence updates)
    last_posted = db.query(LiveBetSnapshot).filter(
        LiveBetSnapshot.recommendation_id == recommendation_id,
        LiveBetSnapshot.alert_sent == True,
        LiveBetSnapshot.alert_type == "high_confidence"
    ).order_by(LiveBetSnapshot.created_at.desc()).first()

    should_alert = False
    discord_sent = False
    previous_prob = None

    if alert_type == "high_confidence":
        # High confidence alert logic:
        # - First time reaching 80%: post
        # - After that: only post if probability increased by 5%+ since last post
        if not last_posted:
            # First time reaching 80%+
            should_alert = True
        else:
            # Check if probability increased by 5%+ since last post
            previous_prob = last_posted.live_probability
            prob_increase = calc["live_probability"] - previous_prob
            if prob_increase >= 0.05:  # 5% increase
                should_alert = True

    elif alert_type == "cashout":
        # Cashout: only post once
        existing_cashout = db.query(LiveBetSnapshot).filter(
            LiveBetSnapshot.recommendation_id == recommendation_id,
            LiveBetSnapshot.alert_type == "cashout",
            LiveBetSnapshot.alert_sent == True
        ).first()
        if not existing_cashout:
            should_alert = True

    # Send Discord alert if warranted
    if should_alert:
        snapshot.alert_sent = True
        snapshot.alert_type = alert_type

        discord_sent = send_live_tracking_alert(
            game=game,
            rec=rec,
            pred=pred,
            live_probability=calc["live_probability"],
            alert_type=alert_type,
            current_scores={
                'home': game.final_home_score or 0,
                'away': game.final_away_score or 0
            },
            period=game.period,
            clock=game.clock or "0:00",
            previous_probability=previous_prob,
        )

    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)

    return {
        "status": "success",
        "snapshot_id": snapshot.id,
        "live_probability": calc["live_probability"],
        "alert_type": alert_type,
        "should_alert": should_alert,
        "discord_sent": discord_sent,
        "details": calc,
    }


@app.get("/api/live-tracking/alerts")
def get_pending_live_alerts(db: Session = Depends(get_db)):
    """Get pending alerts for live bet tracking (>=80% or <=20% probability)."""
    # Get recent snapshots with alerts
    recent_time = datetime.utcnow() - timedelta(hours=3)

    alerts = db.query(LiveBetSnapshot).filter(
        LiveBetSnapshot.alert_sent == True,
        LiveBetSnapshot.alert_type != None,
        LiveBetSnapshot.created_at >= recent_time
    ).order_by(LiveBetSnapshot.created_at.desc()).limit(20).all()

    results = []
    for snap in alerts:
        rec = db.query(BettingRecommendation).filter(
            BettingRecommendation.id == snap.recommendation_id
        ).first()
        pred = db.query(Prediction).filter(Prediction.id == snap.prediction_id).first()
        game = db.query(Game).filter(Game.id == snap.game_id).first()

        results.append({
            "id": snap.id,
            "alert_type": snap.alert_type,
            "live_probability": snap.live_probability,
            "period": snap.period,
            "clock": snap.clock,
            "home_score": snap.home_score,
            "away_score": snap.away_score,
            "bet_type": snap.bet_type,
            "pick": snap.bet_pick,
            "line": snap.bet_line,
            "game": f"{game.away_team} @ {game.home_team}" if game else None,
            "created_at": snap.created_at.isoformat(),
        })

    return {"alerts": results}


@app.get("/api/live-tracking/active")
def get_active_tracked_games(db: Session = Depends(get_db)):
    """Get all games with active live tracking."""
    # Get games that are in progress and have predictions
    active_games = db.query(Game).filter(
        Game.game_status != "Final",
        Game.game_status != "Scheduled",
        Game.period > 0
    ).all()

    results = []
    for game in active_games:
        # Check if game has predictions
        preds = db.query(Prediction).filter(Prediction.game_id == game.id).all()
        if not preds:
            continue

        # Get live tracking info
        tracking = get_live_tracking_for_game(game.id, db)
        results.append(tracking)

    return {"active_games": results, "count": len(results)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

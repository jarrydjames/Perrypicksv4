#!/usr/bin/env python3
"""
PerryPicks Unified Startup Script

Starts all components:
- Backend API server (FastAPI)
- Automation service (game monitoring, predictions, Discord posting)
- Optional: Frontend dev server

On startup:
- Initializes database
- Refreshes data as needed
- Queues pending halftime triggers
- Posts to Discord when triggers fire

Usage:
    python start.py                    # Start backend + automation
    python start.py --with-frontend    # Also start frontend
    python start.py --no-discord       # Run without Discord posting
"""

import argparse
import atexit
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, date
from pathlib import Path

import pandas as pd

# Load .env file before other imports
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")
from pathlib import Path
from typing import List, Optional, Set
from dataclasses import dataclass, field

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("PerryPicks")
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)


# =============================================================================
# SINGLE INSTANCE LOCK - Prevents duplicate processes
# =============================================================================

PID_FILE = Path(__file__).parent / ".perrypicks.pid"
HEARTBEAT_FILE = Path(__file__).parent / ".perrypicks.heartbeat"
LOCK_ACQUIRED = False


def is_process_running(pid: int) -> bool:
    """Check if a process with the given PID is running."""
    try:
        os.kill(pid, 0)  # Signal 0 doesn't kill, just checks if process exists
        return True
    except (OSError, ProcessLookupError):
        return False


def acquire_lock() -> bool:
    """
    Acquire a single-instance lock.

    Returns:
        True if lock acquired successfully, False if another instance is running
    """
    global LOCK_ACQUIRED

    # Clean up old cleanup files (more than 1 minute old)
    # These are created during graceful shutdown and should be cleaned up
    for cleanup_file in Path.cwd().glob("*.pid.cleaning"):
        try:
            mtime = datetime.fromtimestamp(cleanup_file.stat().st_mtime)
            age = datetime.now() - mtime
            if age > timedelta(minutes=1):
                logger.info(f"Removing old cleanup file: {cleanup_file}")
                cleanup_file.unlink()
        except:
            pass

    # Check for existing PID file
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())

            # Check if that process is still running
            if is_process_running(old_pid):
                logger.error(f"Another PerryPicks instance is already running (PID {old_pid})")
                logger.error(f"If this is incorrect, delete {PID_FILE} and try again")
                return False
            else:
                # Stale PID file - process crashed without cleanup
                # Add grace period to prevent race condition during cleanup
                try:
                    # Check file modification time
                    mtime = datetime.fromtimestamp(PID_FILE.stat().st_mtime)
                    age = datetime.now() - mtime
                    
                    # If PID file is less than 30 seconds old, wait for cleanup to complete
                    if age < timedelta(seconds=30):
                        logger.warning(f"Recent PID file (age: {age.total_seconds():.1f}s) - possible cleanup in progress")
                        logger.warning(f"Waiting 5 seconds for cleanup to complete...")
                        time.sleep(5)
                        
                        # Check again if process started
                        if is_process_running(old_pid):
                            logger.error(f"Process started during grace period - aborting")
                            return False
                except:
                    pass
                
                logger.warning(f"Removing stale PID file (process {old_pid} no longer exists)")
                PID_FILE.unlink()
        except (ValueError, OSError) as e:
            logger.warning(f"Corrupt PID file, removing: {e}")
            PID_FILE.unlink()

    # Write our PID
    try:
        PID_FILE.write_text(str(os.getpid()))
        LOCK_ACQUIRED = True
        logger.info(f"Acquired process lock (PID {os.getpid()})")
        return True
    except OSError as e:
        logger.error(f"Failed to write PID file: {e}")
        return False


def release_lock():
    """Release the single-instance lock.
    
    IMPORTANT: Only remove PID file if this is the process that owns it.
    This prevents race conditions during cleanup.
    """
    global LOCK_ACQUIRED

    if LOCK_ACQUIRED and PID_FILE.exists():
        try:
            current_pid = int(PID_FILE.read_text().strip())
            # Only remove PID file if we own it
            if current_pid == os.getpid():
                # Don't remove immediately - let new instances wait for grace period
                # Move to temporary name instead
                temp_file = PID_FILE.with_suffix('.pid.cleaning')
                PID_FILE.rename(temp_file)
                logger.info("Released process lock (moved to cleanup file)")
        except (ValueError, OSError):
            pass
    LOCK_ACQUIRED = False


def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown."""
    def handle_shutdown(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        release_lock()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)


# =============================================================================
# END SINGLE INSTANCE LOCK
# =============================================================================


@dataclass
class PendingTrigger:
    """A pending trigger waiting to fire."""
    game_id: str
    trigger_type: str  # halftime, q3_5min
    queued_at: datetime
    fired: bool = False
    posted: bool = False


class PerryPicksOrchestrator:
    """
    Main orchestrator that manages all PerryPicks components.

    Responsibilities:
    - Start/stop backend API
    - Start/stop automation service
    - Manage pending trigger queue
    - Coordinate prediction -> odds -> recommendation -> Discord flow
    """

    POLL_INTERVAL = 30  # seconds
    ODDS_CACHE_TTL = 60  # seconds - odds are only fetched when trigger fires
    DATA_REFRESH_HOUR = 6  # Refresh data at 6 AM CST (12:00 UTC)
    DATA_REFRESH_INTERVAL_HOURS = 6  # Also refresh every 6 hours as backup

    def __init__(
        self,
        discord_webhook_url: Optional[str] = None,
        start_backend: bool = True,
        start_frontend: bool = False,
        backend_port: int = 8000,
        frontend_port: int = 3000,
    ):
        self.discord_webhook_url = discord_webhook_url
        self.start_backend = start_backend
        self.start_frontend = start_frontend
        self.backend_port = backend_port
        self.frontend_port = frontend_port

        self._running = False
        self._processes: List[subprocess.Popen] = []
        self._pending_triggers: List[PendingTrigger] = []
        self._fired_triggers: Set[str] = set()  # game_id:trigger_type
        self._threads: List[threading.Thread] = []
        self._last_data_refresh: Optional[datetime] = None
        self._last_report_card_date: Optional[str] = None  # Track last report card date (YYYY-MM-DD)
        self._last_queue_date: Optional[str] = None  # Track last queue date for daily cleanup
        self._trigger_lock = threading.Lock()  # Lock for thread-safe trigger processing

        # Components (loaded lazily)
        self._predictor = None
        self._feature_store = None
        self._discord_client = None
        self._game_monitor = None
        self._db = None

        # Note: Signal handlers are already set up in main() via setup_signal_handlers()
        # No need to register them again here

    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signal."""
        logger.info("Shutdown signal received...")
        self._running = False

    def start(self):
        """Start all components."""
        logger.info("=" * 60)
        logger.info("Starting PerryPicks")
        logger.info("=" * 60)

        self._running = True

        try:
            # 1. Initialize database
            self._init_database()

            # 2. Load ML model
            self._load_predictor()

            # 3. Initialize Discord client
            if self.discord_webhook_url:
                self._init_discord()

                # Send service started alert
                if hasattr(self, '_alert_manager') and self._alert_manager:
                    self._alert_manager.service_started()

            # 4. Start local Odds API (free ESPN odds)
            self._start_odds_api()

            # 5. Start backend API
            if self.start_backend:
                self._start_backend()

            # 6. Start frontend (optional)
            if self.start_frontend:
                self._start_frontend()

            # 7. Initial data refresh
            self._refresh_data()

            # 8. Check for unposted predictions from previous runs (CRITICAL FIX)
            self._retry_unposted_predictions()

            # 9. Queue pending triggers for today's games
            self._queue_todays_games()

            # 10. Start main automation loop
            self._run_automation_loop()

        except Exception as e:
            logger.error(f"Startup failed: {e}")
            # Send critical alert for startup failure
            if hasattr(self, '_alert_manager') and self._alert_manager:
                self._alert_manager.critical("Startup Failed", str(e))
            raise
        finally:
            self._cleanup()

    def _init_database(self):
        """Initialize database and ensure tables exist."""
        logger.info("Initializing database...")
        from dashboard.backend.database import init_db, SessionLocal, Game, Prediction, GhostBettorConfig

        init_db()

        # Verify database is accessible
        db = SessionLocal()
        try:
            config = db.query(GhostBettorConfig).first()
            if config:
                logger.info(f"Database ready - Bankroll: ${config.current_bankroll}")
        finally:
            db.close()

    def _load_predictor(self):
        """Load the REPTAR prediction model and feature store."""
        logger.info("Loading REPTAR prediction model...")
        from src.models.reptar_predictor import get_predictor
        from src.features.temporal_store import get_feature_store

        # Check data staleness before loading
        self._check_and_refresh_stale_data()

        self._predictor = get_predictor()
        self._feature_store = get_feature_store()
        logger.info("REPTAR model and feature store loaded successfully")

    def _check_and_refresh_stale_data(self):
        """Check if temporal data is stale and refresh if needed."""
        import pandas as pd
        from pathlib import Path

        store_path = Path("data/processed/halftime_with_refined_temporal.parquet")

        if not store_path.exists():
            logger.warning("Temporal feature store not found, will refresh...")
            self._refresh_temporal_data()
            return

        try:
            df = pd.read_parquet(store_path)
            if 'game_date' in df.columns:
                df['game_date'] = pd.to_datetime(df['game_date'], errors='coerce', utc=True)
                latest_game = df['game_date'].max()
                now = pd.Timestamp.now(tz='UTC')
                days_stale = (now - latest_game).days

                if days_stale > 1:
                    logger.warning(f"Temporal data is {days_stale} days stale, refreshing...")
                    self._refresh_temporal_data()
                else:
                    logger.info(f"Temporal data is current ({days_stale} days stale)")
                    self._last_data_refresh = datetime.utcnow()
        except Exception as e:
            logger.warning(f"Could not check data staleness: {e}")

    def _init_discord(self):
        """Initialize Discord client and multi-channel router."""
        logger.info("Initializing Discord client and channel router...")
        from src.automation.discord_client import DiscordClient
        from src.automation.channel_router import ChannelRouter
        from src.automation.remediation import init_alert_system

        self._discord_client = DiscordClient(self.discord_webhook_url)

        # Initialize multi-channel router for different alert types
        self._channel_router = ChannelRouter(
            main_webhook=os.environ.get("DISCORD_WEBHOOK_URL"),
            high_confidence_webhook=os.environ.get("DISCORD_HIGH_CONFIDENCE_WEBHOOK"),
            sgp_webhook=os.environ.get("DISCORD_SGP_WEBHOOK"),
            report_card_webhook=os.environ.get("DISCORD_REPORT_CARD_WEBHOOK"),
            alerts_webhook=os.environ.get("DISCORD_ALERTS_WEBHOOK"),
            post_to_main_always=True,
        )

        # Initialize alert system with alerts webhook
        alerts_webhook = os.environ.get("DISCORD_ALERTS_WEBHOOK")
        self._alert_manager = init_alert_system(
            discord_client=self._discord_client,
            alerts_webhook_url=alerts_webhook,
        )

        # Log which channels are configured
        channels_configured = ["MAIN"]
        if os.environ.get("DISCORD_HIGH_CONFIDENCE_WEBHOOK"):
            channels_configured.append("HIGH_CONFIDENCE")
        if os.environ.get("DISCORD_SGP_WEBHOOK"):
            channels_configured.append("SGP")
        if os.environ.get("DISCORD_ALERTS_WEBHOOK"):
            channels_configured.append("ALERTS")

        logger.info(f"Discord channels configured: {', '.join(channels_configured)}")

    def _start_odds_api(self):
        """Start the local Odds API server."""
        logger.info("Starting local Odds API on port 8890...")

        odds_api_dir = Path(__file__).parent.parent / "Odds_Api"
        odds_api_main = odds_api_dir / "app" / "main.py"

        if not odds_api_main.exists():
            logger.warning(f"Odds API not found at {odds_api_main}, skipping")
            return False

        # Set environment to use composite provider (ESPN for pre-game, DraftKings Live for in-game)
        # This provides odds for both pre-game AND live/halftime situations
        # Pass only essential environment variables to avoid validation errors in odds_api
env = {
    "PATH": os.environ.get("PATH", ""),
    "HOME": os.environ.get("HOME", ""),
    "ODDS_PROVIDER": "composite",
    "PORT": "8890",
}

        # Activate venv if it exists
        venv_python = odds_api_dir / ".venv" / "bin" / "python"
        python_cmd = str(venv_python) if venv_python.exists() else sys.executable

        odds_log_path = Path(__file__).parent / "logs" / "odds_api_subprocess.log"
        odds_log_fh = open(odds_log_path, "a", buffering=1)

        process = subprocess.Popen(
            [python_cmd, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8890"],
            cwd=str(odds_api_dir),
            stdout=odds_log_fh,
            stderr=subprocess.STDOUT,
            env=env,
        )
        self._processes.append(process)

        # Wait for Odds API to be ready
        time.sleep(5)
        import requests
        for attempt in range(60):
            try:
                resp = requests.get("http://localhost:8890/v1/health", timeout=2)
                if resp.status_code == 200:
                    logger.info("Odds API ready at http://localhost:8890")
                    # Set environment variable for PerryPicks to use local Odds API
                    os.environ["ODDS_API_BASE_URL"] = "http://localhost:8890"
                    os.environ["USE_LOCAL_ODDS_API"] = "true"
                    return True
            except:
                time.sleep(1)

        # CRITICAL FIX: Health check failed - don't use local API
        logger.error("Odds API failed to start after 60 attempts - will use external API")
        os.environ["USE_LOCAL_ODDS_API"] = "false"
        return False

    def _start_backend(self):
        """Start the FastAPI backend server."""
        logger.info(f"Starting backend API on port {self.backend_port}...")

        backend_log_path = Path(__file__).parent / "logs" / "backend_subprocess.log"
        backend_log_fh = open(backend_log_path, "a", buffering=1)

        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "dashboard.backend.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                str(self.backend_port),
            ],
            cwd=str(Path(__file__).parent),
            stdout=backend_log_fh,
            stderr=subprocess.STDOUT,
            env={**os.environ},
        )
        self._processes.append(process)

        # Wait for backend to be ready
        time.sleep(2)
        import requests
        for _ in range(10):
            try:
                resp = requests.get(f"http://localhost:{self.backend_port}/api/health", timeout=2)
                if resp.status_code == 200:
                    logger.info(f"Backend API ready at http://localhost:{self.backend_port}")
                    return
            except:
                time.sleep(1)

        logger.warning("Backend may not be fully ready yet")

    def _start_frontend(self):
        """Start the frontend dev server."""
        logger.info(f"Starting frontend on port {self.frontend_port}...")

        frontend_dir = Path(__file__).parent / "dashboard" / "frontend"

        process = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=str(frontend_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self._processes.append(process)

        logger.info(f"Frontend starting at http://localhost:{self.frontend_port}")

    def _cleanup_stale_games(self):
        """Remove games from database that aren't in today's schedule."""
        from dashboard.backend.database import SessionLocal, Game, Prediction
        from src.schedule import fetch_schedule

        try:
            db = SessionLocal()
            today = date.today().strftime('%Y-%m-%d')
            schedule = fetch_schedule(today)
            valid_ids = set(g.get('nba_id') for g in schedule.get('games', []))

            if not valid_ids:
                return

            today_start = datetime(date.today().year, date.today().month, date.today().day)
            stale = db.query(Game).filter(
                Game.game_date >= today_start,
                ~Game.nba_id.in_(valid_ids)
            ).all()

            if stale:
                for g in stale:
                    # Delete associated predictions first to avoid NOT NULL constraint
                    db.query(Prediction).filter(Prediction.game_id == g.id).delete()
                    db.delete(g)
                db.commit()
                logger.info(f"Cleaned up {len(stale)} stale games from database")

            db.close()
        except Exception as e:
            logger.warning(f"Failed to cleanup stale games: {e}")

    def _retry_unposted_predictions(self):
        """Retry any unposted predictions from previous runs.

        CRITICAL: This ensures predictions that failed to post get retried
        even after process restart.
        """
        from dashboard.backend.database import SessionLocal, Prediction, Game, PredictionStatus

        try:
            db = SessionLocal()
            # Find unposted predictions from today
            today_start = datetime(date.today().year, date.today().month, date.today().day)
            unposted = db.query(Prediction).join(Game).filter(
                Game.game_date >= today_start,
                Prediction.posted_to_discord == False,
                Prediction.status == PredictionStatus.PENDING
            ).all()

            if unposted:
                logger.warning(f"Found {len(unposted)} unposted predictions - these will be retried")
                # Delete them so they can be recreated fresh
                for pred in unposted:
                    logger.info(f"Deleting unposted prediction {pred.id} for game {pred.game_id}")
                    db.delete(pred)
                db.commit()
                logger.info("Unposted predictions cleared - will be recreated on next trigger")
            else:
                logger.debug("No unposted predictions found")

            db.close()
        except Exception as e:
            logger.warning(f"Failed to check unposted predictions: {e}")

    def _refresh_data(self):
        """Refresh any data needed on startup."""
        logger.info("Refreshing data...")

        # Import here to avoid circular imports
        from dashboard.backend.database import SessionLocal, Game
        from src.schedule import fetch_schedule
        from datetime import date

        # Use local date (games are scheduled in Eastern time)
        today = date.today().strftime("%Y-%m-%d")

        try:
            schedule = fetch_schedule(today)
            games = schedule.get("games", [])
            logger.info(f"Found {len(games)} games for today ({today})")

            # Store games in database
            db = SessionLocal()
            try:
                for game_data in games:
                    nba_id = game_data.get("nba_id")
                    if not nba_id:
                        continue

                    existing = db.query(Game).filter(Game.nba_id == nba_id).first()
                    if not existing:
                        # Parse game date from ESPN data (ISO format: 2026-02-28T00:00Z)
                        date_time_str = game_data.get("date_time", "")
                        if date_time_str:
                            game_datetime = datetime.fromisoformat(date_time_str.replace("Z", "+00:00"))
                        else:
                            # Fallback to current time if no date provided
                            game_datetime = datetime.utcnow()

                        game = Game(
                            nba_id=nba_id,
                            game_date=game_datetime,
                            home_team=game_data.get("home_team", ""),
                            away_team=game_data.get("away_team", ""),
                            home_team_name=game_data.get("home_name"),
                            away_team_name=game_data.get("away_name"),
                            game_status="Scheduled",
                        )
                        db.add(game)

                db.commit()
            finally:
                db.close()

        except Exception as e:
            logger.error(f"Failed to refresh schedule: {e}")

    def _queue_todays_games(self):
        """Queue pending triggers for today's games."""
        logger.info("Queueing today's games for monitoring...")

        # First, clean up any stale games from previous runs
        self._cleanup_stale_games()

        from src.schedule import fetch_schedule
        from datetime import date

        # Use local date (games are scheduled in Eastern time)
        today = date.today().strftime("%Y-%m-%d")

        # DAILY CLEANUP: Clear triggers and threads for new day
        # This prevents memory leaks from accumulating over days
        if hasattr(self, '_last_queue_date') and self._last_queue_date != today:
            logger.info("New day detected - clearing old triggers and threads")
            self._pending_triggers.clear()
            self._fired_triggers.clear()
            # Clean up finished threads
            self._threads = [t for t in self._threads if t.is_alive()]
        self._last_queue_date = today

        try:
            schedule = fetch_schedule(today)
            games = schedule.get("games", [])

            for game in games:
                nba_id = game.get("nba_id")
                if not nba_id:
                    continue

                # Skip if already queued (prevents duplicates on refresh)
                trigger_key_halftime = f"{nba_id}:halftime"
                trigger_key_q3 = f"{nba_id}:q3_5min"
                existing_keys = {f"{t.game_id}:{t.trigger_type}" for t in self._pending_triggers}

                if trigger_key_halftime not in existing_keys and trigger_key_halftime not in self._fired_triggers:
                    # Queue halftime trigger
                    self._pending_triggers.append(PendingTrigger(
                        game_id=nba_id,
                        trigger_type="halftime",
                        queued_at=datetime.utcnow(),
                    ))

                # Q3 TRIGGER DISABLED - model not configured yet
                # if trigger_key_q3 not in existing_keys and trigger_key_q3 not in self._fired_triggers:
                #     # Queue Q3 5min trigger
                #     self._pending_triggers.append(PendingTrigger(
                #         game_id=nba_id,
                #         trigger_type="q3_5min",
                #         queued_at=datetime.utcnow(),
                #     ))

            logger.info(f"Queued {len(self._pending_triggers)} pending triggers for {len(games)} games")

        except Exception as e:
            logger.error(f"Failed to queue games: {e}")

    # Tricode mapping (ESPN -> NBA CDN)
    TRICODE_MAP = {
        'WSH': 'WAS',  # Washington
        'PHX': 'PHO',  # Phoenix
        'SA': 'SAS',   # San Antonio
        'GS': 'GSW',   # Golden State
        'NY': 'NYK',   # New York
        'NO': 'NOP',   # New Orleans
        'UTAH': 'UTA', # Utah Jazz (ESPN returns full name)
        'BKN': 'BKN',  # Brooklyn (already correct)
        'BK': 'BKN',   # Brooklyn (alternate)
    }

    # Mapping from tricodes to full team names (for odds API)
    TRICODE_TO_FULL_NAME = {
        'ATL': 'Atlanta Hawks',
        'BOS': 'Boston Celtics',
        'BKN': 'Brooklyn Nets',
        'CHA': 'Charlotte Hornets',
        'CHI': 'Chicago Bulls',
        'CLE': 'Cleveland Cavaliers',
        'DAL': 'Dallas Mavericks',
        'DEN': 'Denver Nuggets',
        'DET': 'Detroit Pistons',
        'GSW': 'Golden State Warriors',
        'HOU': 'Houston Rockets',
        'IND': 'Indiana Pacers',
        'LAC': 'Los Angeles Clippers',
        'LAL': 'Los Angeles Lakers',
        'MEM': 'Memphis Grizzlies',
        'MIA': 'Miami Heat',
        'MIL': 'Milwaukee Bucks',
        'MIN': 'Minnesota Timberwolves',
        'NOP': 'New Orleans Pelicans',
        'NYK': 'New York Knicks',
        'OKC': 'Oklahoma City Thunder',
        'ORL': 'Orlando Magic',
        'PHI': 'Philadelphia 76ers',
        'PHO': 'Phoenix Suns',  # NBA CDN uses PHO
        'POR': 'Portland Trail Blazers',
        'SAC': 'Sacramento Kings',
        'SAS': 'San Antonio Spurs',
        'TOR': 'Toronto Raptors',
        'UTA': 'Utah Jazz',
        'WAS': 'Washington Wizards',
    }

    def _normalize_tricode(self, code):
        """Normalize tricode to match NBA CDN format."""
        return self.TRICODE_MAP.get(code, code)

    def _tricode_to_full_name(self, tricode: str) -> str:
        """Convert tricode to full team name for odds API."""
        if not tricode:
            return "UNKNOWN"
        return self.TRICODE_TO_FULL_NAME.get(tricode.upper(), tricode)

    def _update_game_statuses(self):
        """Update game statuses from ESPN scoreboard."""
        from dashboard.backend.database import SessionLocal, Game
        from datetime import date as date_type
        import requests

        try:
            # Use local date (ESPN uses Eastern time for scheduling)
            today = date_type.today().strftime("%Y%m%d")

            # Fetch live scores from ESPN
            url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={today}"
            resp = requests.get(url, timeout=10)
            data = resp.json()

            events = data.get("events", [])

            db = SessionLocal()
            try:
                updated = 0
                for event in events:
                    # Extract team info from event
                    competitions = event.get("competitions", [])
                    if not competitions:
                        continue

                    comp = competitions[0]
                    home_team = None
                    away_team = None
                    home_name = None
                    away_name = None
                    home_score = 0
                    away_score = 0

                    for competitor in comp.get("competitors", []):
                        team = competitor.get("team", {})
                        tricode = team.get("abbreviation", "")
                        name = team.get("displayName", "")
                        score = competitor.get("score", "0")
                        if competitor.get("homeAway") == "home":
                            home_team = tricode
                            home_name = name
                            try:
                                home_score = int(score)
                            except:
                                home_score = 0
                        else:
                            away_team = tricode
                            away_name = name
                            try:
                                away_score = int(score)
                            except:
                                away_score = 0

                    if not home_team or not away_team:
                        continue

                    # Normalize tricodes to match NBA CDN format
                    home_team_norm = self._normalize_tricode(home_team)
                    away_team_norm = self._normalize_tricode(away_team)

                    # CRITICAL FIX: Match by tricodes first (most reliable)
                    # Use date filter to ensure we get today's game
                    game = db.query(Game).filter(
                        Game.home_team == home_team_norm,
                        Game.away_team == away_team_norm,
                        Game.game_date >= datetime(date_type.today().year, date_type.today().month, date_type.today().day)
                    ).first()

                    # If not found, try without date filter (for edge cases)
                    if not game:
                        game = db.query(Game).filter(
                            Game.home_team == home_team_norm,
                            Game.away_team == away_team_norm
                        ).first()

                    # Only try team names as last resort (often None in our DB)
                    if not game and home_name and away_name:
                        game = db.query(Game).filter(
                            Game.home_team_name == home_name,
                            Game.away_team_name == away_name
                        ).first()

                    if not game:
                        # Game doesn't exist in our DB, skip it
                        continue

                    # Get status
                    status_type = event.get("status", {}).get("type", {})
                    status_name = status_type.get("name", "STATUS_SCHEDULED")
                    short_detail = status_type.get("shortDetail", "")

                    # Parse period and clock from shortDetail (e.g., "1:26 - 2nd" or "Halftime")
                    period = 0
                    clock = ""
                    if short_detail:
                        # Try to parse "clock - period" format
                        if " - " in short_detail:
                            parts = short_detail.split(" - ")
                            clock_part = parts[0].strip()
                            period_part = parts[1].strip() if len(parts) > 1 else ""

                            # Extract clock
                            clock = clock_part if ":" in clock_part or clock_part.replace(".", "").isdigit() else ""

                            # Extract period number
                            period_map = {"1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "ot": 5, "2ot": 6}
                            for k, v in period_map.items():
                                if k in period_part.lower():
                                    period = v
                                    break
                        elif "halftime" in short_detail.lower():
                            period = 2
                            clock = "0:00"
                            status_name = "STATUS_HALFTIME"

                    # Map ESPN status to our status
                    if status_name == "STATUS_FINAL":
                        game_status = "Final"
                    elif status_name == "STATUS_IN_PROGRESS":
                        game_status = short_detail if short_detail else "In Progress"
                    elif status_name == "STATUS_HALFTIME":
                        game_status = "Halftime"
                    elif status_name == "STATUS_SCHEDULED":
                        game_status = "Scheduled"
                    else:
                        game_status = short_detail or "Scheduled"

                    # Update game
                    game.game_status = game_status
                    game.final_home_score = home_score
                    game.final_away_score = away_score
                    game.period = period
                    game.clock = clock
                    updated += 1

                db.commit()
                if updated > 0:
                    logger.info(f"Updated {updated} game statuses from ESPN")

            finally:
                db.close()

        except Exception as e:
            logger.debug(f"Failed to update game statuses: {e}")

    def _check_and_queue_games(self):
        """Check if date changed and re-queue games if needed."""
        from datetime import date
        today = date.today().strftime("%Y-%m-%d")
        
        if self._last_queue_date != today:
            logger.info(f"Date changed from {self._last_queue_date} to {today}, re-queuing games")
            self._queue_todays_games()

    def _run_automation_loop(self):
        """Main automation loop - checks triggers and processes them."""
        logger.info("Starting automation loop...")
        logger.info(f"Polling interval: {self.POLL_INTERVAL}s")
        logger.info("Odds will be fetched only when triggers fire (saves API credits)")
        logger.info(f"Temporal data will refresh daily at {self.DATA_REFRESH_HOUR}:00 CST and every {self.DATA_REFRESH_INTERVAL_HOURS} hours")
        logger.info("Live bet tracking enabled for Q3/Q4 games")

        try:
            HEARTBEAT_FILE.write_text(datetime.utcnow().isoformat())
        except Exception:
            pass

        iteration = 0
        while self._running:
            try:
                try:
                    HEARTBEAT_FILE.write_text(datetime.utcnow().isoformat())
                except Exception:
                    pass

                # Update game statuses every 2 iterations (60s with 30s interval)
                if iteration % 2 == 0:
                    self._update_game_statuses()
                    # Resolve bets for completed games
                    self._resolve_bets()

                # Check if we should refresh temporal data
                if self._should_refresh_data():
                    logger.info("Starting scheduled temporal data refresh...")
                    self._refresh_temporal_data()

                # Check if we should post daily report card (6 AM CST / 12:00 UTC)
                if self._should_post_report_card():
                    logger.info("Posting daily report card...")
                    self._post_daily_report_card()

                # Run live bet tracking every 4 iterations (2 minutes with 30s interval)
                if iteration % 4 == 0:
                    self._run_live_tracking()

                # Clean up finished threads every 10 iterations (5 minutes)
                if iteration % 10 == 0:
                    alive_count = len([t for t in self._threads if t.is_alive()])
                    if alive_count < len(self._threads):
                        self._threads = [t for t in self._threads if t.is_alive()]
                        logger.debug(f"Cleaned up {len(self._threads) - alive_count} finished threads")

                # Check if date changed and re-queue games (every 2 minutes)
                if iteration % 4 == 0:
                    self._check_and_queue_games()

                self._poll_and_process()
                iteration += 1
                time.sleep(self.POLL_INTERVAL)
            except Exception as e:
                logger.error(f"Error in automation loop: {e}")
                try:
                    HEARTBEAT_FILE.write_text(datetime.utcnow().isoformat())
                except Exception:
                    pass
                time.sleep(self.POLL_INTERVAL)

    def _should_refresh_data(self) -> bool:
        """Check if we should refresh temporal data.

        Refresh conditions:
        1. Never refreshed before
        2. It's 6 AM CST (12:00 UTC) and we haven't refreshed today
        3. More than DATA_REFRESH_INTERVAL_HOURS since last refresh
        """
        now = datetime.utcnow()

        # Never refreshed - should refresh
        if self._last_data_refresh is None:
            return True

        # Check if it's been more than REFRESH_INTERVAL hours
        hours_since_refresh = (now - self._last_data_refresh).total_seconds() / 3600
        if hours_since_refresh >= self.DATA_REFRESH_INTERVAL_HOURS:
            return True

        return False

    def _refresh_temporal_data(self):
        """Refresh temporal feature store with latest completed games."""
        try:
            from src.data.refresh_temporal import refresh_temporal_store
            from src.features.temporal_store import get_feature_store

            # Run the refresh
            added = refresh_temporal_store(days=7)

            # Reload the feature store
            store = get_feature_store()
            store._loaded = False
            store.load()

            self._last_data_refresh = datetime.utcnow()
            logger.info(f"Temporal data refresh complete: added {added} games, feature store reloaded")

        except Exception as e:
            logger.error(f"Failed to refresh temporal data: {e}")

    def _should_post_report_card(self) -> bool:
        """Check if we should post the daily report card.

        Posts at 6 AM CST (12:00 UTC) after all games from previous day are complete.
        Only posts once per day.
        """
        from datetime import timezone

        now = datetime.utcnow()
        today_str = now.strftime("%Y-%m-%d")

        # Already posted today
        if self._last_report_card_date == today_str:
            return False

        # Check if it's 6 AM CST (12:00 UTC) or later
        # Report card posts at 12:00 UTC (6 AM CST / 7 AM CDT)
        if now.hour >= 12:
            return True

        return False

    def _post_daily_report_card(self):
        """Generate and post the daily report card to Discord."""
        try:
            from src.automation.report_card import generate_daily_report_card
            from datetime import timedelta
            # Always report on YESTERDAY's date
            # Report cards are posted at 06:00 to summarize the previous day's results
            # This ensures we don't accidentally report on today's games if they finished early
            report_date = datetime.utcnow() - timedelta(days=1)
            logger.info(f"Generating report card for yesterday: {report_date.strftime('%Y-%m-%d')}")

            report = generate_daily_report_card(report_date)

            # Post to report card channel
            if hasattr(self, '_channel_router') and self._channel_router:
                result = self._channel_router.post_report_card(report)
                if result and result.success:
                    logger.info("Daily report card posted successfully")
                    self._last_report_card_date = datetime.utcnow().strftime("%Y-%m-%d")
                else:
                    error = result.error if result else "Unknown error"
                    logger.error(f"Failed to post report card: {error}")
            else:
                logger.warning("No channel router available for report card")

        except Exception as e:
            logger.error(f"Failed to post daily report card: {e}")

    def _resolve_bets(self):
        """
        Resolve betting recommendations and parlays for completed games.

        Called after game statuses are updated. Resolves:
        - BettingRecommendation records (total, spread, ML, team_total)
        - Parlay records (based on leg results)
        """
        try:
            from src.automation.bet_resolver import run_bet_resolution

            resolved_bets, resolved_parlays, errors = run_bet_resolution()

            if resolved_bets > 0 or resolved_parlays > 0:
                logger.info(f"Bet resolution: {resolved_bets} bets, {resolved_parlays} parlays resolved")
                if errors > 0:
                    logger.warning(f"Bet resolution had {errors} errors")

        except Exception as e:
            logger.error(f"Failed to resolve bets: {e}")

    def _run_live_tracking(self):
        """
        Run live bet probability tracking for games in progress.

        For games in Q3/Q4 with pending halftime recommendations:
        - Create probability snapshots
        - Send Discord alerts when probability crosses thresholds (80%+/20%-)
        """
        import requests
        from dashboard.backend.database import SessionLocal, Game, Prediction, BettingRecommendation, BetStatus

        try:
            db = SessionLocal()
            try:
                # Find games in progress (Q3 or Q4, not Final)
                in_progress_games = db.query(Game).filter(
                    Game.period >= 3,
                    Game.period <= 4,
                    Game.game_status != "Final",
                ).all()

                if not in_progress_games:
                    return

                logger.info(f"Live tracking: checking {len(in_progress_games)} game(s) in progress")

                for game in in_progress_games:
                    # Find predictions for this game
                    predictions = db.query(Prediction).filter(
                        Prediction.game_id == game.id,
                        Prediction.trigger_type == "halftime",
                    ).all()

                    for pred in predictions:
                        # Find pending recommendations
                        recommendations = db.query(BettingRecommendation).filter(
                            BettingRecommendation.prediction_id == pred.id,
                            BettingRecommendation.result == BetStatus.PENDING,
                        ).all()

                        for rec in recommendations:
                            try:
                                # Call the live tracking API to create a snapshot
                                resp = requests.post(
                                    f"http://localhost:8000/api/live-tracking/snapshot/{rec.id}",
                                    timeout=10,
                                )
                                if resp.status_code == 200:
                                    data = resp.json()
                                    prob = data.get("live_probability", 0) * 100
                                    alert_type = data.get("alert_type")
                                    discord_sent = data.get("discord_sent", False)

                                    if alert_type:
                                        logger.info(
                                            f"Live tracking: {game.away_team}@{game.home_team} "
                                            f"{rec.pick} {rec.bet_type.value} - {prob:.0f}% "
                                            f"[{alert_type}{' - Discord sent!' if discord_sent else ''}]"
                                        )
                                    else:
                                        logger.debug(
                                            f"Live tracking: {game.away_team}@{game.home_team} "
                                            f"{rec.pick} {rec.bet_type.value} - {prob:.0f}%"
                                        )
                            except Exception as e:
                                logger.debug(f"Failed to create snapshot for rec {rec.id}: {e}")

            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error in live tracking: {e}")

    def _poll_and_process(self):
        """Poll games and process any fired triggers."""
        from src.data.game_data import fetch_box, get_game_info

        for trigger in self._pending_triggers:
            if trigger.fired:
                continue

            trigger_key = f"{trigger.game_id}:{trigger.trigger_type}"
            if trigger_key in self._fired_triggers:
                continue

            try:
                # Check if trigger should fire
                should_fire = self._check_trigger(trigger)

                if should_fire:
                    # Process triggers in PARALLEL - don't use lock that blocks other games
                    # Check again without lock to prevent race condition
                    if trigger_key in self._fired_triggers:
                        continue

                    logger.info(f"Trigger fired: {trigger_key}")
                    trigger.fired = True
                    self._fired_triggers.add(trigger_key)

                    # Process trigger in a separate thread
                    thread = threading.Thread(
                        target=self._process_trigger,
                        args=(trigger,),
                        daemon=True,
                    )
                    thread.start()
                    self._threads.append(thread)

            except Exception as e:
                logger.error(f"Error checking trigger {trigger_key}: {e}")

    def _check_trigger(self, trigger: PendingTrigger) -> bool:
        """Check if a trigger should fire using database game status."""
        from dashboard.backend.database import SessionLocal, Game

        try:
            db = SessionLocal()
            try:
                # Find game by NBA ID
                game = db.query(Game).filter(Game.nba_id == trigger.game_id).first()
                if not game:
                    logger.debug(f"Game not found for {trigger.game_id}")
                    return False

                status = game.game_status or ""

                # Game is final - no more triggers
                if "Final" in status:
                    trigger.fired = True
                    return False

                if trigger.trigger_type == "halftime":
                    # Check if game is at halftime
                    if "Halftime" in status or "halftime" in status.lower():
                        return True
                    # Also check if status shows end of 2nd quarter
                    if "End of 2nd" in status or "End of 2nd" in status:
                        return True
                    return False

                elif trigger.trigger_type == "q3_5min":
                    # Check if in Q3 with time running down
                    if "Q3" in status or "3rd" in status:
                        # Try to parse clock from status like "5:26 - 3rd"
                        if " - " in status:
                            clock_part = status.split(" - ")[0]
                            minutes = self._parse_clock_minutes(clock_part)
                            if 0 < minutes < 6:
                                return True
                    return False

                return False

            finally:
                db.close()

        except Exception as e:
            logger.debug(f"Could not check game state for {trigger.game_id}: {e}")
            return False

    def _is_halftime(self, clock: str, status: str) -> bool:
        """Check if game is at halftime."""
        # Halftime typically shows as period 2 with no clock or specific status
        if "halftime" in status.lower():
            return True
        if clock == "" or clock == "0:00":
            return True
        return False

    def _parse_clock_minutes(self, clock: str) -> int:
        """Parse minutes from clock string (MM:SS or M.M format)."""
        try:
            if not clock:
                return 0
            clock = clock.strip()
            # Handle "MM:SS" format
            if ":" in clock:
                parts = clock.split(":")
                return int(parts[0])
            # Handle "M.M" decimal format (e.g., "2.1" = 2.1 minutes)
            else:
                return int(float(clock))
        except:
            return 0

    def _process_trigger(self, trigger: PendingTrigger):
        """
        Process a fired trigger:
        1. Generate prediction
        2. Fetch odds (only now - saves API credits!)
        3. Generate betting recommendations
        4. Save to database
        5. Post to Discord
        """
        from src.data.game_data import fetch_box, get_game_info, first_half_score, behavior_counts_1h, fetch_pbp_df, get_efficiency_stats_from_box
        from src.automation.post_generator import PostGenerator
        from dashboard.backend.database import SessionLocal, Game, Prediction, BettingRecommendation, GhostBet, GhostBettorConfig, TriggerType as DBTriggerType, PredictionStatus, BetType
        from src.odds import fetch_nba_odds_snapshot, OddsAPIError

        trigger_key = f"{trigger.game_id}:{trigger.trigger_type}"
        logger.info(f"Processing trigger: {trigger_key}")

        # DUPLICATE PREVENTION: Check if prediction already exists
        db = SessionLocal()
        try:
            trigger_type_enum = DBTriggerType.HALFTIME if trigger.trigger_type == "halftime" else DBTriggerType.Q3_5MIN
            existing = db.query(Prediction).join(Game).filter(
                Game.nba_id == trigger.game_id,
                Prediction.trigger_type == trigger_type_enum
            ).first()
            if existing:
                # If already posted, skip entirely
                if existing.posted_to_discord:
                    logger.warning(f"Prediction already posted for {trigger_key} (ID={existing.id}), skipping duplicate")
                    return
                # If not posted, update the existing prediction instead of creating new one
                logger.info(f"Reposting unposted prediction {trigger_key} (ID={existing.id})")
        finally:
            db.close()

        try:
            # 1. Fetch game data
            box = fetch_box(trigger.game_id)
            info = get_game_info(box)

            game_id_db = None
            db = SessionLocal()
            try:
                # Get or create game record
                game = db.query(Game).filter(Game.nba_id == trigger.game_id).first()
                if not game:
                    # Parse game time from box score (gameTimeUTC field)
                    game_time_str = info.get("game_time", "")
                    if game_time_str:
                        # gameTimeUTC is in format: "2026-02-27T21:00:00Z"
                        try:
                            game_datetime = datetime.fromisoformat(game_time_str)
                        except (ValueError, TypeError):
                            game_datetime = datetime.utcnow()
                    else:
                        game_datetime = datetime.utcnow()

                    game = Game(
                        nba_id=trigger.game_id,
                        game_date=game_datetime,
                        home_team=info.get("home_tricode", "HOME"),
                        away_team=info.get("away_tricode", "AWAY"),
                        home_team_name=info.get("home_name"),
                        away_team_name=info.get("away_name"),
                    )
                    db.add(game)
                    db.commit()
                    db.refresh(game)
                game_id_db = game.id
            finally:
                db.close()

            # 2. Generate prediction
            if trigger.trigger_type == "halftime":
                h1_home, h1_away = first_half_score(box)
                behavior = behavior_counts_1h(fetch_pbp_df(trigger.game_id))

                # Get EFFICIENCY stats from LIVE BOX SCORE (critical for accuracy!)
                efficiency_stats = get_efficiency_stats_from_box(box)

                # Get team IDs and rolling stats from feature store
                home_tri = info.get("home_tricode", "HOME")
                away_tri = info.get("away_tricode", "AWAY")
                target_dt = pd.Timestamp.now(tz='UTC')

                team_stats = {}
                if self._feature_store:
                    try:
                        # Get team IDs
                        home_team_id = self._feature_store.team_tricode_to_id(home_tri)
                        away_team_id = self._feature_store.team_tricode_to_id(away_tri)

                        # Get team features (rolling stats)
                        home_features = self._feature_store.get_team_features(home_team_id, target_dt, "home")
                        away_features = self._feature_store.get_team_features(away_team_id, target_dt, "away")

                        # Merge features for the predictor
                        team_stats = {**home_features, **away_features}
                        team_stats["home_team_id"] = home_team_id
                        team_stats["away_team_id"] = away_team_id

                        logger.info(f"Loaded team stats for {home_tri} (ID={home_team_id}) vs {away_tri} (ID={away_team_id})")
                    except Exception as e:
                        logger.warning(f"Could not load team stats from feature store: {e}, using defaults")

                # CRITICAL: Override with LIVE efficiency stats from box score
                # These are more accurate than pre-computed averages
                team_stats.update(efficiency_stats)
                logger.info(f"Live efficiency stats: home_efg={efficiency_stats.get('home_efg', 0):.3f}, away_efg={efficiency_stats.get('away_efg', 0):.3f}")

                features, pred = self._predictor.predict(h1_home, h1_away, behavior, team_stats)

                prediction_data = {
                    "pred_total": pred["pred_final_total"],
                    "pred_margin": pred["pred_final_margin"],
                    "home_win_prob": pred.get("home_win_prob", 0.5),
                    "total_q10": pred.get("total_q10"),
                    "total_q90": pred.get("total_q90"),
                    "h1_home": h1_home,
                    "h1_away": h1_away,
                }

            elif trigger.trigger_type == "q3_5min":
                # For Q3, we'd need a different prediction method
                # For now, skip or use halftime method
                logger.info(f"Q3 prediction not yet implemented for {trigger.game_id}")
                return
            else:
                logger.warning(f"Unknown trigger type: {trigger.trigger_type}")
                return

            logger.info(
                f"Prediction for {info.get('away_tricode')} @ {info.get('home_tricode')}: "
                f"Total {prediction_data['pred_total']:.1f}, "
                f"Margin {prediction_data['pred_margin']:+.1f}, "
                f"Home Win {prediction_data['home_win_prob']:.1%}"
            )

            # 3. Fetch odds - ONLY NOW when trigger fires!
            odds = None
            # Use tricodes to get full team names for odds API
            home_tricode = info.get("home_tricode", "HOME")
            away_tricode = info.get("away_tricode", "AWAY")
            home_name = self._tricode_to_full_name(home_tricode)
            away_name = self._tricode_to_full_name(away_tricode)
            logger.info(f"Converted tricodes to full names: {home_tricode} -> {home_name}, {away_tricode} -> {away_name}")

            # ODDS RETRY LOGIC - Try up to 3 times over 3 minutes
            # REDUCED FROM 8 to 3 to prevent blocking first game
            max_retries = 3
            import time
            
            for retry_attempt in range(max_retries):
                try:
                    logger.info(f"Fetching live odds for {home_name} vs {away_name}... (attempt {retry_attempt + 1}/{max_retries})")
                    snapshot = fetch_nba_odds_snapshot(
                        home_name=home_name,
                        away_name=away_name,
                        timeout_s=60,  # Give DraftKings Live more time
                    )
                    odds = {
                        "total_points": snapshot.total_points,
                        "total_over_odds": snapshot.total_over_odds,
                        "total_under_odds": snapshot.total_under_odds,
                        "spread_home": snapshot.spread_home,
                        "spread_home_odds": snapshot.spread_home_odds,
                        "spread_away_odds": snapshot.spread_away_odds,
                        "moneyline_home": snapshot.moneyline_home,
                        "moneyline_away": snapshot.moneyline_away,
                        "team_total_home": getattr(snapshot, 'team_total_home', None),
                        "team_total_home_over_odds": getattr(snapshot, 'team_total_home_over_odds', None),
                        "team_total_home_under_odds": getattr(snapshot, 'team_total_home_under_odds', None),
                        "team_total_away": getattr(snapshot, 'team_total_away', None),
                        "team_total_away_over_odds": getattr(snapshot, 'team_total_away_over_odds', None),
                        "team_total_away_under_odds": getattr(snapshot, 'team_total_away_under_odds', None),
                        "bookmaker": snapshot.bookmaker,
                    }
                    logger.info(f"Live odds: Total {odds['total_points']}, Spread {odds['spread_home']}, Team Totals {odds['team_total_home']}/{odds['team_total_away']} from {odds['bookmaker']}")
                    break  # Success! Exit retry loop
                    
                except OddsAPIError as e:
                    if retry_attempt < max_retries - 1:
                        logger.warning(f"Odds not available (attempt {retry_attempt + 1}/{max_retries}): {e}, retrying in 60 seconds...")
                        time.sleep(60)
                    else:
                        # Final attempt failed, try ESPN fallback
                        logger.warning(f"Live odds not found after {max_retries} attempts: {e}, trying ESPN pregame fallback...")
                        try:
                            import requests
                            espn_url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={trigger.game_id}"
                            resp = requests.get(espn_url, timeout=10)
                            if resp.status_code == 200:
                                data = resp.json()
                                # Extract pregame odds from ESPN
                                picks = data.get("pickcenter", [])
                                if picks:
                                    pick = picks[0]  # Use first bookmaker
                                    total_points = pick.get("overUnder")
                                    spread_home = pick.get("spread")

                                    # CRITICAL FIX: Validate odds data before using
                                    if total_points is None and spread_home is None:
                                        logger.warning("ESPN fallback returned no valid odds, posting without odds")
                                    else:
                                        odds = {
                                            "total_points": total_points,
                                            "total_over_odds": -110,
                                            "total_under_odds": -110,
                                            "spread_home": spread_home,
                                            "spread_home_odds": -110,
                                            "spread_away_odds": -110,
                                            "moneyline_home": None,
                                            "moneyline_away": None,
                                            "bookmaker": pick.get("provider", {}).get("name", "ESPN"),
                                        }
                                        logger.info(f"ESPN fallback odds: Total {total_points or 'N/A'}, Spread {spread_home or 'N/A'}")
                        except Exception as espn_e:
                            logger.warning(f"ESPN fallback also failed: {espn_e}")
                            
                except Exception as e:
                    if retry_attempt < max_retries - 1:
                        logger.error(f"Odds fetch error (attempt {retry_attempt + 1}/{max_retries}): {e}, retrying in 60 seconds...")
                        time.sleep(60)
                    else:
                        logger.error(f"Odds fetch error after {max_retries} attempts: {e}")

            # 4. Generate betting recommendations with team names
            home_tri = info.get("home_tricode", "HOME")
            away_tri = info.get("away_tricode", "AWAY")
            recommendations, passed_bets = self._generate_recommendations(prediction_data, odds, home_team=home_tri, away_team=away_tri)

            # 5. Save prediction to database
            db = SessionLocal()
            try:
                prediction = Prediction(
                    game_id=game_id_db,
                    trigger_type=DBTriggerType.HALFTIME if trigger.trigger_type == "halftime" else DBTriggerType.Q3_5MIN,
                    h1_home=prediction_data.get("h1_home"),
                    h1_away=prediction_data.get("h1_away"),
                    pred_total=prediction_data["pred_total"],
                    pred_margin=prediction_data["pred_margin"],
                    pred_winner=info.get("home_tricode") if prediction_data["pred_margin"] > 0 else info.get("away_tricode"),
                    home_win_prob=prediction_data["home_win_prob"],
                    total_q10=prediction_data.get("total_q10"),
                    total_q90=prediction_data.get("total_q90"),
                    status=PredictionStatus.PENDING,
                    posted_to_discord=False,
                )
                db.add(prediction)
                db.commit()
                db.refresh(prediction)

                # Save betting recommendations
                for rec in recommendations:
                    # Convert bet_type string to enum
                    bet_type_str = rec["bet_type"].lower()
                    bet_type_map = {
                        "total": BetType.TOTAL,
                        "spread": BetType.SPREAD,
                        "moneyline": BetType.MONEYLINE,
                        "ml": BetType.MONEYLINE,
                        "team_total": BetType.TEAM_TOTAL,
                    }
                    bet_type_enum = bet_type_map.get(bet_type_str, BetType.TOTAL)

                    bet_rec = BettingRecommendation(
                        prediction_id=prediction.id,
                        bet_type=bet_type_enum,
                        pick=rec["pick"],
                        line=rec.get("line"),
                        odds=rec.get("odds"),
                        edge=rec.get("edge"),
                        probability=rec.get("probability"),
                        confidence_tier=rec.get("confidence_tier"),
                    )
                    db.add(bet_rec)

                db.commit()
                logger.info(f"Saved prediction #{prediction.id} to database")

            finally:
                db.close()

            # 6. Post to Discord and update database with result
            if self._discord_client:
                discord_result = self._post_to_discord(
                    info, prediction_data, odds, recommendations, efficiency_stats, passed_bets,
                    prediction_id=prediction.id, game_id=game.id
                )

                # Update database with Discord posting status
                db = SessionLocal()
                try:
                    db_prediction = db.query(Prediction).filter(Prediction.id == prediction.id).first()
                    if db_prediction:
                        if discord_result and discord_result.success:
                            db_prediction.posted_to_discord = True
                            db_prediction.status = PredictionStatus.POSTED
                            logger.info(f"Updated prediction #{prediction.id} - Discord posted")
                        else:
                            db_prediction.status = PredictionStatus.FAILED
                            error_msg = discord_result.error if discord_result else "Unknown error"
                            logger.error(f"Updated prediction #{prediction.id} - Discord failed: {error_msg}")
                        db.commit()
                except Exception as db_e:
                    logger.error(f"Failed to update prediction status: {db_e}")
                finally:
                    db.close()

            trigger.posted = True
            logger.info(f"Trigger processed successfully: {trigger_key}")

        except Exception as e:
            logger.error(f"Failed to process trigger {trigger_key}: {e}")

    def _is_odds_acceptable(self, odds: int) -> bool:
        """Check if odds are acceptable (not worse than -300).
        
        Args:
            odds: American odds (e.g., -110, -500, +150)
            
        Returns:
            True if odds are acceptable, False if too risky
        """
        if odds is None:
            return True  # No odds info, allow it
        
        try:
            odds_int = int(odds)
            # Reject if odds are worse than -300 (e.g., -500, -900)
            if odds_int < -300:
                logger.debug(f"Rejecting bet with odds {odds_int} (worse than -300)")
                return False
            return True
        except (ValueError, TypeError):
            return True  # If we can't parse, allow it

    def _generate_recommendations(self, prediction: dict, odds: Optional[dict], home_team: str = "HOME", away_team: str = "AWAY") -> tuple:
        """Generate betting recommendations based on prediction and odds.

        Args:
            prediction: Prediction dict with pred_total, pred_margin, home_win_prob
            odds: Odds dict with lines and prices
            home_team: Home team tricode (e.g., "BOS")
            away_team: Away team tricode (e.g., "LAL")

        Returns:
            Tuple of (recommended_bets, passed_bets)
        """
        from src.betting import prob_over_under_from_mean_sd, prob_spread_cover_from_mean_sd, breakeven_prob_from_american

        recommendations = []
        passed_bets = []

        if not odds:
            logger.warning("No odds available - skipping betting recommendations")
            return recommendations, passed_bets

        pred_total = prediction["pred_total"]
        pred_margin = prediction["pred_margin"]
        home_win_prob = prediction["home_win_prob"]
        total_sd = 10.87  # Standard deviation for total predictions
        margin_sd = 7.76  # Standard deviation for margin predictions

        # --- TOTAL ---
        if odds.get("total_points"):
            line = odds["total_points"]
            diff = pred_total - line
            p_over = prob_over_under_from_mean_sd(pred_total, total_sd, line)

            # OVER
            pick = "OVER"
            prob = p_over
            rec_odds = odds.get("total_over_odds", -110)
            meets_threshold = abs(diff) >= 2.0 and prob >= 0.56 and self._is_odds_acceptable(rec_odds)

            rec = {
                "bet_type": "total",
                "pick": f"{pick} {line}",
                "line": line,
                "odds": rec_odds,
                "edge": diff,
                "probability": prob,
                "confidence_tier": "A" if prob >= 0.75 else ("B+" if prob >= 0.65 else "B"),
            }
            if meets_threshold:
                recommendations.append(rec)
            else:
                reason = "edge/prob below threshold" if abs(diff) >= 2.0 and prob >= 0.56 else "odds too risky (< -300)"
                passed_bets.append({**rec, "reason": reason})

            # UNDER
            prob_under = 1 - p_over
            diff_under = -diff
            rec_odds_under = odds.get("total_under_odds", -110)
            meets_threshold_under = abs(diff_under) >= 2.0 and prob_under >= 0.56 and self._is_odds_acceptable(rec_odds_under)

            rec_under = {
                "bet_type": "total",
                "pick": f"UNDER {line}",
                "line": line,
                "odds": rec_odds_under,
                "edge": diff_under,
                "probability": prob_under,
                "confidence_tier": "A" if prob_under >= 0.75 else ("B+" if prob_under >= 0.65 else "B"),
            }
            if meets_threshold_under:
                recommendations.append(rec_under)
            else:
                reason = "edge/prob below threshold" if abs(diff_under) >= 2.0 and prob_under >= 0.56 else "odds too risky (< -300)"
                passed_bets.append({**rec_under, "reason": reason})

        # --- SPREAD ---
        if odds.get("spread_home"):
            spread = odds["spread_home"]
            edge = pred_margin + spread
            p_home_cover = prob_spread_cover_from_mean_sd(pred_margin, margin_sd, spread)

            # Home team spread
            pick_team = home_team
            prob = p_home_cover
            rec_odds = odds.get("spread_home_odds", -110)
            pick_line = f"{spread:+.1f}"
            meets_threshold = abs(edge) >= 1.5 and prob >= 0.57 and self._is_odds_acceptable(rec_odds)

            rec = {
                "bet_type": "spread",
                "pick": f"{pick_team} {pick_line}",
                "line": spread,
                "odds": rec_odds,
                "edge": edge,
                "probability": prob,
                "confidence_tier": "A" if prob >= 0.75 else ("B+" if prob >= 0.65 else "B"),
            }
            if meets_threshold:
                recommendations.append(rec)
            else:
                reason = "edge/prob below threshold" if abs(edge) >= 1.5 and prob >= 0.57 else "odds too risky (< -300)"
                passed_bets.append({**rec, "reason": reason})

            # Away team spread
            edge_away = -edge
            prob_away = 1 - p_home_cover
            rec_odds_away = odds.get("spread_away_odds", -110)
            pick_line_away = f"{-spread:+.1f}"
            meets_threshold_away = abs(edge_away) >= 1.5 and prob_away >= 0.57 and self._is_odds_acceptable(rec_odds_away)

            rec_away = {
                "bet_type": "spread",
                "pick": f"{away_team} {pick_line_away}",
                "line": -spread,
                "odds": rec_odds_away,
                "edge": edge_away,
                "probability": prob_away,
                "confidence_tier": "A" if prob_away >= 0.75 else ("B+" if prob_away >= 0.65 else "B"),
            }
            if meets_threshold_away:
                recommendations.append(rec_away)
            else:
                reason = "edge/prob below threshold" if abs(edge_away) >= 1.5 and prob_away >= 0.57 else "odds too risky (< -300)"
                passed_bets.append({**rec_away, "reason": reason})

        # --- MONEYLINE ---
        if odds.get("moneyline_home") and odds.get("moneyline_away"):
            try:
                home_be = breakeven_prob_from_american(int(odds["moneyline_home"]))
                away_be = breakeven_prob_from_american(int(odds["moneyline_away"]))

                home_ml_edge = home_win_prob - home_be
                away_ml_edge = (1 - home_win_prob) - away_be

                # Home ML
                meets_threshold_home = home_ml_edge >= 0.03 and home_win_prob >= 0.58 and self._is_odds_acceptable(odds["moneyline_home"])
                rec_home = {
                    "bet_type": "ml",
                    "pick": f"{home_team} ML",
                    "odds": odds["moneyline_home"],
                    "edge": home_ml_edge,
                    "probability": home_win_prob,
                    "confidence_tier": "A" if home_win_prob >= 0.75 else ("B+" if home_win_prob >= 0.70 else "B"),
                }
                if meets_threshold_home:
                    recommendations.append(rec_home)
                else:
                    reason = "edge/prob below threshold" if home_ml_edge >= 0.03 and home_win_prob >= 0.58 else "odds too risky (< -300)"
                    passed_bets.append({**rec_home, "reason": reason})

                # Away ML
                away_win_prob = 1 - home_win_prob
                meets_threshold_away = away_ml_edge >= 0.03 and away_win_prob >= 0.58 and self._is_odds_acceptable(odds["moneyline_away"])
                rec_away = {
                    "bet_type": "ml",
                    "pick": f"{away_team} ML",
                    "odds": odds["moneyline_away"],
                    "edge": away_ml_edge,
                    "probability": away_win_prob,
                    "confidence_tier": "A" if away_win_prob >= 0.75 else ("B+" if away_win_prob >= 0.70 else "B"),
                }
                if meets_threshold_away:
                    recommendations.append(rec_away)
                else:
                    reason = "edge/prob below threshold" if away_ml_edge >= 0.03 and away_win_prob >= 0.58 else "odds too risky (< -300)"
                    passed_bets.append({**rec_away, "reason": reason})

            except (ValueError, TypeError) as e:
                logger.warning(f"Could not process moneyline odds: {e}")

        # --- TEAM TOTALS ---
        # Derive predicted team totals from game total and margin
        # pred_home = (total + margin) / 2, pred_away = (total - margin) / 2
        pred_home_score = (pred_total + pred_margin) / 2
        pred_away_score = (pred_total - pred_margin) / 2
        team_total_sd = total_sd * 0.7  # Team totals have lower variance than game totals

        # DERIVE TEAM TOTALS IF NOT AVAILABLE FROM BOOKMAKER
        # This allows us to generate team total recommendations even when
        # the bookmaker doesn't provide them directly
        if odds.get("team_total_home") is None and odds.get("team_total_away") is None and odds.get("total_points") is not None and odds.get("spread_home") is not None:
            total = odds["total_points"]
            spread = odds["spread_home"]
            
            # Sportsbook convention: spread_home is the HOME line (negative when home is favored).
            # We want: home_total + away_total = total
            #          home_total - away_total = -spread_home
            # Therefore:
            #   home_total = (total - spread_home) / 2
            #   away_total = (total + spread_home) / 2
            # Example: Total 230, Spread -5.5 -> Home = (230 - (-5.5)) / 2 = 117.75
            #                           Away = (230 + (-5.5)) / 2 = 112.25
            derived_home = (total - spread) / 2.0
            derived_away = (total + spread) / 2.0

            # Sanity: if home is favored (spread < 0) but derived_home < derived_away, swap.
            if spread < 0 and derived_home < derived_away:
                derived_home, derived_away = derived_away, derived_home
            # Sanity: if home is dog (spread > 0) but derived_home > derived_away, swap.
            if spread > 0 and derived_home > derived_away:
                derived_home, derived_away = derived_away, derived_home
            
            odds["team_total_home"] = derived_home
            odds["team_total_away"] = derived_away
            odds["team_total_home_over_odds"] = -110  # Default to -110 for derived
            odds["team_total_home_under_odds"] = -110
            odds["team_total_away_over_odds"] = -110
            odds["team_total_away_under_odds"] = -110
            
            logger.info(f"Derived team totals: Home {derived_home:.1f}, Away {derived_away:.1f} (from Total {total}, Spread {spread})")

        # Home team total
        if odds.get("team_total_home"):
            tt_line = odds["team_total_home"]
            p_over = prob_over_under_from_mean_sd(pred_home_score, team_total_sd, tt_line)
            p_under = 1 - p_over
            edge_over = pred_home_score - tt_line
            edge_under = tt_line - pred_home_score

            # Home Over
            meets_threshold = edge_over >= 1.5 and p_over >= 0.56 and self._is_odds_acceptable(odds.get("team_total_home_over_odds", -110))
            rec = {
                "bet_type": "team_total",
                "pick": f"{home_team} OVER {tt_line}",
                "line": tt_line,
                "odds": odds.get("team_total_home_over_odds", -110),
                "edge": edge_over,
                "probability": p_over,
                "confidence_tier": "A" if p_over >= 0.75 else ("B+" if p_over >= 0.65 else "B"),
            }
            if meets_threshold:
                recommendations.append(rec)
            else:
                reason = "edge/prob below threshold" if edge_over >= 1.5 and p_over >= 0.56 else "odds too risky (< -300)"
                passed_bets.append({**rec, "reason": reason})

            # Home Under
            meets_threshold = edge_under >= 1.5 and p_under >= 0.56 and self._is_odds_acceptable(odds.get("team_total_home_under_odds", -110))
            rec = {
                "bet_type": "team_total",
                "pick": f"{home_team} UNDER {tt_line}",
                "line": tt_line,
                "odds": odds.get("team_total_home_under_odds", -110),
                "edge": edge_under,
                "probability": p_under,
                "confidence_tier": "A" if p_under >= 0.75 else ("B+" if p_under >= 0.65 else "B"),
            }
            if meets_threshold:
                recommendations.append(rec)
            else:
                reason = "edge/prob below threshold" if edge_under >= 1.5 and p_under >= 0.56 else "odds too risky (< -300)"
                passed_bets.append({**rec, "reason": reason})

        # Away team total
        if odds.get("team_total_away"):
            tt_line = odds["team_total_away"]
            p_over = prob_over_under_from_mean_sd(pred_away_score, team_total_sd, tt_line)
            p_under = 1 - p_over
            edge_over = pred_away_score - tt_line
            edge_under = tt_line - pred_away_score

            # Away Over
            meets_threshold = edge_over >= 1.5 and p_over >= 0.56 and self._is_odds_acceptable(odds.get("team_total_away_over_odds", -110))
            rec = {
                "bet_type": "team_total",
                "pick": f"{away_team} OVER {tt_line}",
                "line": tt_line,
                "odds": odds.get("team_total_away_over_odds", -110),
                "edge": edge_over,
                "probability": p_over,
                "confidence_tier": "A" if p_over >= 0.75 else ("B+" if p_over >= 0.65 else "B"),
            }
            if meets_threshold:
                recommendations.append(rec)
            else:
                reason = "edge/prob below threshold" if edge_over >= 1.5 and p_over >= 0.56 else "odds too risky (< -300)"
                passed_bets.append({**rec, "reason": reason})

            # Away Under
            meets_threshold = edge_under >= 1.5 and p_under >= 0.56 and self._is_odds_acceptable(odds.get("team_total_away_under_odds", -110))
            rec = {
                "bet_type": "team_total",
                "pick": f"{away_team} UNDER {tt_line}",
                "line": tt_line,
                "odds": odds.get("team_total_away_under_odds", -110),
                "edge": edge_under,
                "probability": p_under,
                "confidence_tier": "A" if p_under >= 0.75 else ("B+" if p_under >= 0.65 else "B"),
            }
            if meets_threshold:
                recommendations.append(rec)
            else:
                reason = "edge/prob below threshold" if edge_under >= 1.5 and p_under >= 0.56 else "odds too risky (< -300)"
                passed_bets.append({**rec, "reason": reason})

        # Sort recommendations by probability (descending)
        recommendations.sort(key=lambda r: r["probability"], reverse=True)

        # Sort passed bets by bet type for clean display
        type_order = {"total": 0, "spread": 1, "ml": 2, "team_total": 3}
        passed_bets.sort(key=lambda r: (type_order.get(r["bet_type"], 99), r["pick"]))

        logger.info(f"Generated {len(recommendations)} recommendations, {len(passed_bets)} passed")
        return recommendations[:3], passed_bets  # Max 3 recommendations

    def _post_to_discord(self, game_info: dict, prediction: dict, odds: Optional[dict], recommendations: List[dict], efficiency_stats: Optional[dict] = None, passed_bets: Optional[List[dict]] = None, prediction_id: Optional[int] = None, game_id: Optional[int] = None):
        """Post prediction to Discord with improved formatting.

        Args:
            game_info: Game information dict
            prediction: Prediction dict
            odds: Current odds dict
            recommendations: List of recommended bets
            efficiency_stats: Live efficiency stats
            passed_bets: Bets that were evaluated but passed
            prediction_id: Database prediction ID (for parlay tracking)
            game_id: Database game ID (for parlay tracking)
        """
        """Post prediction to Discord with improved formatting."""
        try:
            # Build message content
            away_team = game_info.get("away_tricode", "AWAY")
            home_team = game_info.get("home_tricode", "HOME")
            h1_away = prediction.get("h1_away", 0)
            h1_home = prediction.get("h1_home", 0)
            pred_total = prediction.get("pred_total", 0)
            pred_margin = prediction.get("pred_margin", 0)
            home_win_prob = prediction.get("home_win_prob", 0.5)

            # Calculate projected final scores
            pred_home_score = (pred_total + pred_margin) / 2
            pred_away_score = (pred_total - pred_margin) / 2

            # Determine winner and their probability
            if pred_margin > 0:
                winner_team = home_team
                winner_prob = home_win_prob
            else:
                winner_team = away_team
                winner_prob = 1 - home_win_prob

            # Build message with new format
            lines = [
                "🔥 HALFTIME PREDICTION",
                "",
                f"**{away_team} @ {home_team}** | {h1_away}-{h1_home} at the break",
                "",
                "---",
                "",
                "**REPTAR MODEL PROJECTION**",
                f"Final: {away_team} {pred_away_score:.0f} - {home_team} {pred_home_score:.0f}",
                f"Total: {pred_total:.1f} | Margin: {winner_team} {abs(pred_margin):.1f}",
                f"Win Probability: {winner_team} {winner_prob:.0%}",
                f"Team Totals: {away_team} {pred_away_score:.1f} | {home_team} {pred_home_score:.1f}",
            ]

            if prediction.get("total_q10") and prediction.get("total_q90"):
                lines.append(f"80% CI (Total): {prediction['total_q10']:.0f} - {prediction['total_q90']:.0f}")

            # Add live efficiency stats if available
            if efficiency_stats:
                home_efg = efficiency_stats.get("home_efg", 0) * 100
                home_tor = efficiency_stats.get("home_tor", 0) * 100
                away_efg = efficiency_stats.get("away_efg", 0) * 100
                away_tor = efficiency_stats.get("away_tor", 0) * 100

                lines.extend([
                    "",
                    "---",
                    "",
                    "**LIVE EFFICIENCY (1H)**",
                    f"{home_team}: eFG {home_efg:.1f}% | TOR {home_tor:.1f}%",
                    f"{away_team}: eFG {away_efg:.1f}% | TOR {away_tor:.1f}%",
                ])

            # Add betting recommendations with detailed format
            lines.extend(["", "---", "", "**BETTING RECOMMENDATIONS**"])

            recs_for_take = []  # Store for Perry's Take

            if recommendations:
                for rec in recommendations:
                    tier = rec.get("confidence_tier", "B")
                    pick = rec["pick"]
                    edge = rec.get("edge", 0)
                    prob = rec.get("probability", 0)
                    odds_str = f" ({rec['odds']})" if rec.get("odds") else ""
                    bet_type = rec.get("bet_type", "unknown")

                    # Emoji based on bet type and confidence
                    if tier == "A":
                        emoji = "🎯"
                    elif tier == "B+":
                        emoji = "✅"
                    else:
                        emoji = "⚠️"

                    # Format edge based on bet type
                    if bet_type == "ml":
                        edge_str = f"Edge: {edge:.0%}"
                    else:
                        edge_str = f"Edge: {edge:+.1f} pts"

                    # Probability label based on bet type
                    if bet_type == "total":
                        prob_label = "Hit Prob"
                    elif bet_type == "spread":
                        prob_label = "Cover Prob"
                    else:
                        prob_label = "Win Prob"

                    lines.append(f"{emoji} **{pick.upper()}**{odds_str}")
                    lines.append(f"{edge_str} | {prob_label}: {prob:.1%} | Confidence: {tier}")
                    lines.append("")

                    recs_for_take.append({
                        "pick": pick,
                        "edge": edge,
                        "prob": prob,
                        "probability": prob,  # For channel router
                        "tier": tier,
                        "confidence_tier": tier,  # For channel router
                        "bet_type": bet_type,
                    })
            elif odds:
                # No recommendations but we have odds
                if odds.get("total_points"):
                    lines.append(f"⚠️ **TOTAL**: Pass (Model: {pred_total:.1f} vs Line: {odds['total_points']})")
                if odds.get("spread_home"):
                    lines.append(f"⚠️ **SPREAD**: Pass (Model: {pred_margin:+.1f} vs Line: {odds['spread_home']})")

            # Add passed bets section - show what was evaluated but didn't meet thresholds
            if passed_bets:
                lines.append("")
                lines.append("📋 **Evaluated (Pass)**")

                # Group passed bets by type
                passed_by_type = {}
                for bet in passed_bets:
                    bet_type = bet.get("bet_type", "other").lower()
                    if bet_type == "ml":
                        bet_type = "ML"
                    elif bet_type == "total":
                        bet_type = "Total"
                    elif bet_type == "spread":
                        bet_type = "Spread"
                    elif bet_type == "team_total":
                        bet_type = "Team Total"
                    if bet_type not in passed_by_type:
                        passed_by_type[bet_type] = []
                    passed_by_type[bet_type].append(bet.get("pick", ""))

                for bet_type in ["Total", "Spread", "ML", "Team Total"]:
                    if bet_type in passed_by_type:
                        picks = passed_by_type[bet_type]
                        lines.append(f"   {bet_type}: {', '.join(picks)}")

            # Perry's Take - AI-style summary
            lines.extend(["---", "", "**PERRY'S TAKE**"])

            # Generate take based on game state
            take_parts = []

            # Game closeness assessment
            if abs(pred_margin) <= 3:
                take_parts.append("Tight game projected.")
            elif abs(pred_margin) <= 7:
                take_parts.append("Moderate spread expected.")
            else:
                take_parts.append(f"Clear edge to {winner_team}.")

            # Top recommendation analysis
            if recs_for_take:
                top_rec = max(recs_for_take, key=lambda r: r["prob"])
                pick_desc = top_rec["pick"]
                edge_val = top_rec["edge"]
                edge_desc = f"{abs(edge_val):.1f}-point edge" if top_rec["bet_type"] != "ml" else f"{abs(edge_val):.0%} edge"

                if top_rec["tier"] == "A":
                    take_parts.append(f"The {edge_desc} on {pick_desc} is strong.")
                else:
                    take_parts.append(f"Moderate edge on {pick_desc}.")

            # Efficiency analysis if available
            if efficiency_stats:
                home_efg = efficiency_stats.get("home_efg", 0) * 100
                home_tor = efficiency_stats.get("home_tor", 0) * 100
                away_efg = efficiency_stats.get("away_efg", 0) * 100
                away_tor = efficiency_stats.get("away_tor", 0) * 100

                # Identify notable efficiency stats
                if home_efg >= 58:
                    take_parts.append(f"{home_team}'s eFG ({home_efg:.1f}%) is elite.")
                if away_efg >= 58:
                    take_parts.append(f"{away_team}'s eFG ({away_efg:.1f}%) is elite.")
                if home_tor >= 18:
                    take_parts.append(f"{home_team}'s TOR ({home_tor:.1f}%) is concerning.")
                if away_tor >= 18:
                    take_parts.append(f"{away_team}'s TOR ({away_tor:.1f}%) is concerning.")

            # Final recommendation
            if recs_for_take:
                top_recs = [r for r in recs_for_take if r["tier"] == "A"]
                if top_recs:
                    take_parts.append(f"Take {', '.join([r['pick'] for r in top_recs[:2]])}.")
                else:
                    take_parts.append("Proceed with caution on these plays.")
            else:
                take_parts.append("No strong edges detected - pass on this game.")

            lines.append(" ".join(take_parts))

            content = "\n".join(lines)

            # Post to Discord using multi-channel router
            # This routes to MAIN, HIGH_CONFIDENCE, and SGP channels based on content
            if hasattr(self, '_channel_router') and self._channel_router:
                from src.automation.channel_router import ChannelType

                # Add team info to prediction for channel router
                prediction_with_teams = {
                    **prediction,
                    "away_team": away_team,
                    "home_team": home_team,
                }

                results = self._channel_router.route_prediction(
                    content=content,
                    prediction=prediction_with_teams,
                    recommendations=recs_for_take,
                )

                # Check if at least one channel succeeded
                main_result = results.get(ChannelType.MAIN)
                sgp_result = results.get(ChannelType.SGP)

                # Track parlay if SGP was posted successfully
                if sgp_result and sgp_result.success and prediction_id and game_id:
                    self._save_parlay_tracking(game_id, prediction_id, recs_for_take, prediction_with_teams)

                if main_result and main_result.success:
                    logger.info(f"Posted to Discord channels: {list(results.keys())}")
                    return main_result
                else:
                    # Return the main result even if failed (for database tracking)
                    logger.error(f"Discord post failed on all channels")
                    return main_result
            else:
                # Fallback to single channel if router not available
                result = self._discord_client.post_message(content)

                if result.success:
                    logger.info(f"Posted to Discord successfully")
                else:
                    logger.error(f"Failed to post to Discord: {result.error}")

                return result  # Return result so caller can update database

        except Exception as e:
            logger.error(f"Discord post error: {e}")
            return None  # Return None on exception

    def _save_parlay_tracking(self, game_id: int, prediction_id: int, recommendations: List[dict], prediction: dict):
        """Save parlay to database when SGP is posted.

        Args:
            game_id: Database game ID
            prediction_id: Database prediction ID
            recommendations: List of recommendation dicts that could form parlay
            prediction: Prediction dict with team info
        """
        try:
            from src.automation.report_card import save_parlay_from_recommendations

            home_team = prediction.get("home_team", "HOME")
            away_team = prediction.get("away_team", "AWAY")

            # Get SGP picks using the same logic as channel router
            from src.automation.channel_router import ChannelRouter
            router = ChannelRouter.__new__(ChannelRouter)
            sgp_picks = router._get_sgp_picks(recommendations, home_team, away_team)

            if len(sgp_picks) >= 2:
                # Calculate combined probability
                combined_prob = router._calculate_combined_probability(sgp_picks)

                # Save to database
                parlay_id = save_parlay_from_recommendations(
                    game_id=game_id,
                    prediction_id=prediction_id,
                    recommendations=sgp_picks,
                    combined_probability=combined_prob,
                )

                if parlay_id:
                    logger.info(f"Saved parlay #{parlay_id} with {len(sgp_picks)} legs ({combined_prob:.0%} combined)")

        except Exception as e:
            logger.error(f"Failed to save parlay tracking: {e}")

    def _cleanup(self):
        """Clean up all resources."""
        logger.info("Cleaning up...")

        # Send shutdown alert before closing Discord
        if hasattr(self, '_alert_manager') and self._alert_manager:
            self._alert_manager.service_shutdown("Cleanup initiated")

        # Stop all subprocesses
        for process in self._processes:
            try:
                process.terminate()
                process.wait(timeout=5)
            except:
                try:
                    process.kill()
                except:
                    pass

        # Close Discord client
        if self._discord_client:
            try:
                self._discord_client.close()
            except:
                pass

        logger.info("Cleanup complete")


def main():
    # ==========================================================================
    # SINGLE INSTANCE LOCK - Must be first thing we do
    # ==========================================================================
    setup_signal_handlers()
    atexit.register(release_lock)

    if not acquire_lock():
        sys.exit(1)
    # ==========================================================================

    parser = argparse.ArgumentParser(
        description="Start PerryPicks - unified startup script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--with-frontend",
        action="store_true",
        help="Also start the frontend dev server",
    )
    parser.add_argument(
        "--no-discord",
        action="store_true",
        help="Disable Discord posting",
    )
    parser.add_argument(
        "--backend-port",
        type=int,
        default=8000,
        help="Backend API port (default: 8000)",
    )
    parser.add_argument(
        "--frontend-port",
        type=int,
        default=3000,
        help="Frontend dev server port (default: 3000)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Get Discord webhook from environment
    discord_webhook = None if args.no_discord else os.environ.get("DISCORD_WEBHOOK_URL")

    if not args.no_discord and not discord_webhook:
        logger.warning("No DISCORD_WEBHOOK_URL set - Discord posting disabled")

    # Create and start orchestrator
    orchestrator = PerryPicksOrchestrator(
        discord_webhook_url=discord_webhook,
        start_backend=True,
        start_frontend=args.with_frontend,
        backend_port=args.backend_port,
        frontend_port=args.frontend_port,
    )

    print("\n" + "=" * 60)
    print("PerryPicks - NBA Prediction System")
    print("Powered by REPTAR CatBoost Model")
    print("=" * 60)
    print(f"Backend API: http://localhost:{args.backend_port}")
    if args.with_frontend:
        print(f"Frontend:    http://localhost:{args.frontend_port}")
    print(f"Discord:     {'Enabled' if discord_webhook else 'Disabled'}")
    print(f"Polling:     Every {orchestrator.POLL_INTERVAL}s")
    print("=" * 60 + "\n")

    try:
        orchestrator.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

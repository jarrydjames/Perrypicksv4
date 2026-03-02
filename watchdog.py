#!/usr/bin/env python3
"""
PerryPicks Health Watchdog

Standalone health monitor that ensures all systems are running and fixes issues automatically.

This process runs independently of the main automation and:
- Monitors all critical components
- Detects crashes and failures
- Automatically restarts failed services
- Alerts on critical issues
- Prevents stuck states

Usage:
    python watchdog.py [--check-interval SECONDS] [--no-restart]

    --check-interval: How often to check (default: 60 seconds)
    --no-restart: Don't restart services, only alert (for debugging)
"""

import argparse
import logging
import os
import psutil
import requests
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Load .env so watchdog can send Discord alerts and use config
try:
    from dotenv import load_dotenv
    load_dotenv(Path.cwd() / '.env')
except Exception:
    pass

from typing import Optional, List, Dict
from src.automation.db_maintenance import run_market_tracking_cleanup


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] WATCHDOG: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("Watchdog")

# Constants
PID_FILE = Path(".perrypicks.pid")
AUTOMATION_HEARTBEAT_FILE = Path(".perrypicks.heartbeat")
WATCHDOG_PID_FILE = Path(".watchdog.pid")
MAXIMUS_PID_FILE = Path(".maximus.pid")
MAXIMUS_HEARTBEAT_FILE = Path(".maximus.heartbeat")
MARKET_TRACK_PID_FILE = Path(".market_tracking.pid")
MARKET_TRACK_HEARTBEAT_FILE = Path(".market_tracking.heartbeat")
AUTOMATION_SCRIPT = Path("start.py")
MAXIMUS_SCRIPT = Path("run_maximus_pregame.py")
MARKET_TRACK_SCRIPT = Path("run_market_tracking.py")
VENV_PYTHON = (Path.cwd() / '.venv' / 'bin' / 'python')


# Log rotation (copytruncate so nohup file handles keep working)
LOG_ROTATE_MAX_BYTES = int(os.environ.get('WATCHDOG_LOG_ROTATE_MAX_BYTES', str(5 * 1024 * 1024)))  # 5MB
LOG_ROTATE_BACKUPS = int(os.environ.get('WATCHDOG_LOG_ROTATE_BACKUPS', '5'))
LOG_ROTATE_EVERY_N_CYCLES = int(os.environ.get('WATCHDOG_LOG_ROTATE_EVERY_N_CYCLES', '5'))

DB_MAINT_EVERY_HOURS = int(os.environ.get('WATCHDOG_DB_MAINT_EVERY_HOURS', '24'))

MARKET_TRACK_HEARTBEAT_MAX_AGE_SECONDS = int(os.environ.get('WATCHDOG_MARKET_TRACK_HEARTBEAT_MAX_AGE_SECONDS', '300'))

AUTOMATION_HEARTBEAT_MAX_AGE_SECONDS = int(os.environ.get('WATCHDOG_AUTOMATION_HEARTBEAT_MAX_AGE_SECONDS', '180'))
MAXIMUS_HEARTBEAT_MAX_AGE_SECONDS = int(os.environ.get('WATCHDOG_MAXIMUS_HEARTBEAT_MAX_AGE_SECONDS', '240'))

LOG_PATHS = [
    Path('watchdog.log'),
    Path('perrypicks_automation.log'),
    Path('maximus.log'),
    Path('market_tracking.log'),
    Path('logs/automation.log'),
    Path('logs/reptar_enforcement.log'),
]

# Ports to monitor
PORTS = {
    "backend": 8000,
    "odds_api": 8890,
}

# Health endpoints
HEALTH_ENDPOINTS = {
    "backend": "http://localhost:8000/api/health",
    "odds_api": "http://localhost:8890/v1/health",
}


class ServiceStatus:
    """Status of a monitored service."""
    def __init__(self, name: str, running: bool, message: str, details: Dict = None):
        self.name = name
        self.running = running
        self.message = message
        self.details = details or {}
        self.last_check = datetime.now()


class Watchdog:
    """
    Standalone health watchdog for PerryPicks.

    Monitors:
    - Main automation process
    - Backend API server
    - Odds API server
    - Database connectivity
    - Memory/CPU usage
    - Stuck states (triggers, date rollover)
    """

    def __init__(self, check_interval: int = 60, auto_restart: bool = True):
        self.check_interval = check_interval
        self.auto_restart = auto_restart
        self._running = False
        self._start_time = datetime.now()
        self._service_history: Dict[str, List[ServiceStatus]] = {}
        self._restart_counts: Dict[str, int] = {}
        self._last_alert_time: Dict[str, datetime] = {}
        self._alert_cooldown = timedelta(minutes=5)  # Don't spam alerts
        self._max_restarts = 3  # Max restarts before stopping
        self._restart_window = timedelta(minutes=30)  # Restart window
        self._restart_history: List[datetime] = []
        self._cycle_count = 0
        self._last_db_maintenance_at: Optional[datetime] = None

    def start(self):
        """Start the watchdog."""
        logger.info("="*60)
        logger.info("PerryPicks Watchdog Starting")
        logger.info("="*60)
        logger.info(f"Check interval: {self.check_interval}s")
        logger.info(f"Auto-restart: {'Enabled' if self.auto_restart else 'Disabled'}")
        logger.info(f"Max restarts: {self._max_restarts} per {self._restart_window}")
        logger.info("")

        # Create PID file
        self._create_pid_file()

        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

        self._running = True
        logger.info("Watchdog started and monitoring...")
        logger.info("")

        # Main loop
        while self._running:
            try:
                self._check_cycle()
                time.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Error in check cycle: {e}")
                time.sleep(10)  # Wait before retrying

    def stop(self):
        """Stop the watchdog."""
        logger.info("Stopping watchdog...")
        self._running = False
        self._cleanup_pid_file()
        logger.info("Watchdog stopped")

    def _create_pid_file(self):
        """Create PID file for this watchdog process."""
        WATCHDOG_PID_FILE.write_text(str(os.getpid()))
        logger.info(f"Watchdog PID file created: {WATCHDOG_PID_FILE}")

    def _cleanup_pid_file(self):
        """Remove PID file."""
        if WATCHDOG_PID_FILE.exists():
            WATCHDOG_PID_FILE.unlink()

    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.stop()
        sys.exit(0)

    def _check_cycle(self):
        """Run a complete health check cycle."""
        logger.info("-" * 40)
        logger.info(f"Health Check Cycle - {datetime.now().strftime('%H:%M:%S')}")

        self._cycle_count += 1
        if self._cycle_count % LOG_ROTATE_EVERY_N_CYCLES == 0:
            self._rotate_logs_if_needed()
            self._run_db_maintenance_if_due()

        # Check all services
        services = []
        services.append(self._check_automation())
        services.append(self._check_maximus())
        services.append(self._check_market_tracking())
        services.append(self._check_duplicate_processes())
        services.append(self._check_backend())
        services.append(self._check_odds_api())
        services.append(self._check_database())
        services.append(self._check_memory())
        services.append(self._check_disk_space())
        services.append(self._check_stuck_states())

        # Log status
        self._log_status(services)

        # Handle failures
        self._handle_failures(services)

        # Store history
        for service in services:
            if service.name not in self._service_history:
                self._service_history[service.name] = []
            self._service_history[service.name].append(service)
            # Keep only last 10 checks
            if len(self._service_history[service.name]) > 10:
                self._service_history[service.name] = self._service_history[service.name][-10:]



    def _run_db_maintenance_if_due(self) -> None:
        """Run lightweight DB maintenance periodically."""
        if DB_MAINT_EVERY_HOURS <= 0:
            return

        now = datetime.now()
        if self._last_db_maintenance_at is not None:
            if (now - self._last_db_maintenance_at) < timedelta(hours=DB_MAINT_EVERY_HOURS):
                return

        try:
            pts_deleted, msgs_deleted, msgs_finalized, msgs_failed = run_market_tracking_cleanup()
            self._last_db_maintenance_at = now
            if pts_deleted or msgs_deleted or msgs_finalized or msgs_failed:
                logger.info(
                    f"DB maintenance: deleted {pts_deleted} points, {msgs_deleted} old finalized; reconciled {msgs_finalized} -> finalized, {msgs_failed} -> failed"
                )
        except Exception as e:
            logger.error(f"DB maintenance failed: {e}")

    def _rotate_logs_if_needed(self) -> None:
        """Rotate large log files to avoid unbounded disk growth."""
        for path in LOG_PATHS:
            self._copytruncate_rotate(path)

    def _copytruncate_rotate(self, path: Path) -> None:
        """Rotate a log file using copytruncate semantics.

        This is safer for nohup redirection because the process keeps writing to
        the same inode/path.
        """
        if not path.exists():
            return

        try:
            size = path.stat().st_size
        except Exception:
            return

        if size < LOG_ROTATE_MAX_BYTES:
            return

        # Shift backups: .(n-1) -> .n
        for i in range(LOG_ROTATE_BACKUPS, 0, -1):
            src = Path(f"{path}.{i}")
            dst = Path(f"{path}.{i+1}")
            if dst.exists() and i >= LOG_ROTATE_BACKUPS:
                try:
                    dst.unlink()
                except Exception:
                    pass
            if src.exists():
                try:
                    src.replace(dst)
                except Exception:
                    pass

        rotated = Path(f"{path}.1")
        try:
            shutil.copyfile(path, rotated)
            with open(path, 'w', encoding='utf-8'):
                pass
            logger.info(f"Rotated log {path} -> {rotated} ({size} bytes)")
        except Exception as e:
            logger.error(f"Failed rotating log {path}: {e}")

    def _check_automation(self) -> ServiceStatus:
        """Check if main automation is running."""
        try:
            # Check PID file
            if not PID_FILE.exists():
                return ServiceStatus(
                    "Automation",
                    running=False,
                    message="No PID file found",
                )

            # Check if process is running
            pid = int(PID_FILE.read_text().strip())
            if not self._is_process_running(pid):
                return ServiceStatus(
                    "Automation",
                    running=False,
                    message=f"Process {pid} not running",
                    details={"pid": pid},
                )

            # Check if process is responsive
            process = psutil.Process(pid)
            cpu_percent = process.cpu_percent(interval=1)
            memory_mb = process.memory_info().rss / 1024 / 1024


            # Heartbeat freshness check (detect stuck-but-alive processes)
            try:
                if AUTOMATION_HEARTBEAT_FILE.exists():
                    age_s = time.time() - AUTOMATION_HEARTBEAT_FILE.stat().st_mtime
                    if age_s > AUTOMATION_HEARTBEAT_MAX_AGE_SECONDS:
                        return ServiceStatus(
                            "Automation",
                            running=False,
                            message=f"Stale heartbeat ({int(age_s)}s)",
                            details={"pid": pid, "age_seconds": int(age_s)},
                        )
                else:
                    return ServiceStatus(
                        "Automation",
                        running=False,
                        message="Missing heartbeat",
                        details={"pid": pid},
                    )
            except Exception as e:
                return ServiceStatus(
                    "Automation",
                    running=False,
                    message=f"Heartbeat check failed: {e}",
                    details={"pid": pid},
                )


            return ServiceStatus(
                "Automation",
                running=True,
                message="Running",
                details={
                    "pid": pid,
                    "cpu_percent": cpu_percent,
                    "memory_mb": memory_mb,
                },
            )

        except Exception as e:
            return ServiceStatus(
                "Automation",
                running=False,
                message=f"Check failed: {e}",
            )


    def _check_maximus(self) -> ServiceStatus:
        """Check if MAXIMUS sidecar is running (pregame + daily summary)."""
        try:
            # Prefer PID file
            if MAXIMUS_PID_FILE.exists():
                pid = int(MAXIMUS_PID_FILE.read_text().strip())
                if self._is_process_running(pid):
                    proc = psutil.Process(pid)
                    cpu_percent = proc.cpu_percent(interval=0.2)
                    memory_mb = proc.memory_info().rss / 1024 / 1024

                    # Heartbeat freshness check (detect stuck-but-alive processes)
                    try:
                        if MAXIMUS_HEARTBEAT_FILE.exists():
                            age_s = time.time() - MAXIMUS_HEARTBEAT_FILE.stat().st_mtime
                            if age_s > MAXIMUS_HEARTBEAT_MAX_AGE_SECONDS:
                                return ServiceStatus(
                                    "MAXIMUS",
                                    running=False,
                                    message=f"Stale heartbeat ({int(age_s)}s)",
                                    details={"pid": pid, "age_seconds": int(age_s)},
                                )
                        else:
                            return ServiceStatus(
                                "MAXIMUS",
                                running=False,
                                message="Missing heartbeat",
                                details={"pid": pid},
                            )
                    except Exception as e:
                        return ServiceStatus(
                            "MAXIMUS",
                            running=False,
                            message=f"Heartbeat check failed: {e}",
                            details={"pid": pid},
                        )

                    return ServiceStatus(
                        "MAXIMUS",
                        running=True,
                        message="Running",
                        details={"pid": pid, "cpu_percent": cpu_percent, "memory_mb": memory_mb},
                    )

            # Fallback: scan process list (PID file might be missing)
            for proc in psutil.process_iter(['pid', 'cmdline']):
                cmdline = proc.info.get('cmdline') or []
                if any('run_maximus_pregame.py' in c for c in cmdline):
                    pid = int(proc.info['pid'])
                    # Repair PID file
                    try:
                        MAXIMUS_PID_FILE.write_text(str(pid))
                    except Exception:
                        pass
                    return ServiceStatus(
                        "MAXIMUS",
                        running=True,
                        message="Running (pid file repaired)",
                        details={"pid": pid},
                    )

            return ServiceStatus(
                "MAXIMUS",
                running=False,
                message="Not running",
            )
        except Exception as e:
            return ServiceStatus(
                "MAXIMUS",
                running=False,
                message=f"Check failed: {e}",
            )


    def _check_market_tracking(self) -> ServiceStatus:
        """Check if Market Tracking sidecar is running."""
        try:
            if MARKET_TRACK_PID_FILE.exists():
                pid = int(MARKET_TRACK_PID_FILE.read_text().strip())
                if self._is_process_running(pid):
                    proc = psutil.Process(pid)
                    cpu_percent = proc.cpu_percent(interval=0.2)
                    memory_mb = proc.memory_info().rss / 1024 / 1024

                    # Heartbeat freshness check (detect stuck-but-alive processes)
                    try:
                        if MARKET_TRACK_HEARTBEAT_FILE.exists():
                            age_s = time.time() - MARKET_TRACK_HEARTBEAT_FILE.stat().st_mtime
                            if age_s > MARKET_TRACK_HEARTBEAT_MAX_AGE_SECONDS:
                                return ServiceStatus(
                                    "Market Tracking",
                                    running=False,
                                    message=f"Stale heartbeat ({int(age_s)}s)",
                                    details={"pid": pid, "age_seconds": int(age_s)},
                                )
                        else:
                            # If it's never written a heartbeat, give it a little grace but still treat as unhealthy
                            return ServiceStatus(
                                "Market Tracking",
                                running=False,
                                message="Missing heartbeat",
                                details={"pid": pid},
                            )
                    except Exception as e:
                        return ServiceStatus(
                            "Market Tracking",
                            running=False,
                            message=f"Heartbeat check failed: {e}",
                            details={"pid": pid},
                        )

                    return ServiceStatus(
                        "Market Tracking",
                        running=True,
                        message="Running",
                        details={"pid": pid, "cpu_percent": cpu_percent, "memory_mb": memory_mb},
                    )

            # Fallback process scan
            for proc in psutil.process_iter(['pid', 'cmdline']):
                cmdline = proc.info.get('cmdline') or []
                if any('run_market_tracking.py' in c for c in cmdline):
                    pid = int(proc.info['pid'])
                    try:
                        MARKET_TRACK_PID_FILE.write_text(str(pid))
                    except Exception:
                        pass
                    return ServiceStatus(
                        "Market Tracking",
                        running=True,
                        message="Running (pid file repaired)",
                        details={"pid": pid},
                    )

            return ServiceStatus("Market Tracking", running=False, message="Not running")
        except Exception as e:
            return ServiceStatus("Market Tracking", running=False, message=f"Check failed: {e}")

    def _check_backend(self) -> ServiceStatus:
        """Check if backend API is running."""
        try:
            url = HEALTH_ENDPOINTS["backend"]
            start = time.time()
            response = requests.get(url, timeout=5)
            latency_ms = (time.time() - start) * 1000

            if response.status_code == 200:
                return ServiceStatus(
                    "Backend API",
                    running=True,
                    message="Healthy",
                    details={"latency_ms": round(latency_ms, 1)},
                )
            else:
                return ServiceStatus(
                    "Backend API",
                    running=False,
                    message=f"HTTP {response.status_code}",
                    details={"status_code": response.status_code},
                )
        except requests.exceptions.RequestException as e:
            return ServiceStatus(
                "Backend API",
                running=False,
                message=f"Not responding: {e}",
            )
        except Exception as e:
            return ServiceStatus(
                "Backend API",
                running=False,
                message=f"Check failed: {e}",
            )

    def _check_odds_api(self) -> ServiceStatus:
        """Check if Odds API is running."""
        try:
            url = HEALTH_ENDPOINTS["odds_api"]
            start = time.time()
            response = requests.get(url, timeout=5)
            latency_ms = (time.time() - start) * 1000

            if response.status_code == 200:
                return ServiceStatus(
                    "Odds API",
                    running=True,
                    message="Healthy",
                    details={"latency_ms": round(latency_ms, 1)},
                )
            else:
                return ServiceStatus(
                    "Odds API",
                    running=False,
                    message=f"HTTP {response.status_code}",
                    details={"status_code": response.status_code},
                )
        except requests.exceptions.RequestException as e:
            return ServiceStatus(
                "Odds API",
                running=False,
                message=f"Not responding: {e}",
            )
        except Exception as e:
            return ServiceStatus(
                "Odds API",
                running=False,
                message=f"Check failed: {e}",
            )

    def _check_database(self) -> ServiceStatus:
        """Check database connectivity."""
        try:
            sys.path.insert(0, str(Path.cwd()))
            from dashboard.backend.database import SessionLocal
            from sqlalchemy import text

            db = SessionLocal()
            try:
                result = db.execute(text("SELECT 1")).fetchone()
                if result and result[0] == 1:
                    return ServiceStatus(
                        "Database",
                        running=True,
                        message="Connected",
                    )
                else:
                    return ServiceStatus(
                        "Database",
                        running=False,
                        message="Query failed",
                    )
            finally:
                db.close()
        except Exception as e:
            return ServiceStatus(
                "Database",
                running=False,
                message=f"Connection failed: {e}",
            )

    def _check_memory(self) -> ServiceStatus:
        """Check system memory usage."""
        try:
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            memory_gb = memory.total / (1024**3)
            available_gb = memory.available / (1024**3)

            if memory_percent < 80:
                status = "Normal"
                running = True
            elif memory_percent < 90:
                status = "High"
                running = True
            else:
                status = "Critical"
                running = False
            return ServiceStatus(
                "Memory",
                running=running,
                message=f"{status} ({memory_percent:.1f}%)",
                details={
                    "memory_percent": memory_percent,
                    "memory_gb": round(memory_gb, 2),
                    "available_gb": round(available_gb, 2),
                },
            )
        except Exception as e:
            return ServiceStatus(
                "Memory",
                running=False,
                message=f"Check failed: {e}",
            )


    def _check_disk_space(self) -> ServiceStatus:
        """Check disk space usage."""
        try:
            disk = psutil.disk_usage('/')
            percent = disk.percent
            free_gb = disk.free / (1024**3)
            total_gb = disk.total / (1024**3)

            if percent < 80:
                status = "Normal"
                running = True
            elif percent < 90:
                status = "High"
                running = True
            else:
                status = "Critical"
                running = False
            return ServiceStatus(
                "Disk Space",
                running=running,
                message=f"{status} ({percent:.1f}%)",
                details={
                    "disk_percent": round(percent, 2),
                    "free_gb": round(free_gb, 2),
                    "total_gb": round(total_gb, 2),
                },
            )
        except Exception as e:
            return ServiceStatus(
                "Disk Space",
                running=False,
                message=f"Check failed: {e}",
            )

    def _check_stuck_states(self) -> ServiceStatus:
        """Check for stuck states (triggers, date rollover, API failures)."""
        try:
            sys.path.insert(0, str(Path.cwd()))
            from dashboard.backend.database import (
                SessionLocal,
                Prediction,
                Game,
                TriggerType as DBTriggerType,
                PredictionStatus as DBPredictionStatus,
            )
            from src.utils.league_time import league_day_str, league_now
            from sqlalchemy import text

            db = SessionLocal()
            issues = []
            details = {}

            try:
                # Check for stale predictions (created > 4 hours ago, not posted)
                four_hours_ago = datetime.now() - timedelta(hours=4)
                stale_predictions = db.query(Prediction).filter(
                    Prediction.created_at < four_hours_ago,
                    Prediction.posted_to_discord == False,
                    Prediction.status.in_([DBPredictionStatus.PENDING, DBPredictionStatus.FAILED]),
                ).count()

                if stale_predictions > 0:
                    issues.append(f"{stale_predictions} stale predictions")
                    details["stale_predictions"] = stale_predictions
                
                # NEW: Check for API failure - games not updating
                # Detects if game statuses aren't being updated (API 403/timeout)
                five_min_ago = datetime.now() - timedelta(minutes=5)
                result = db.execute(text("""
                    SELECT COUNT(*) FROM games
                    WHERE DATE(game_date) = :today
                      AND (updated_at IS NULL OR updated_at < :cutoff)
                      AND game_status NOT IN ('Final', 'Scheduled')
                """), {
                    "today": league_day_str(),
                    "cutoff": five_min_ago
                }).fetchone()
                
                stale_games = result[0] if result else 0
                if stale_games > 0:
                    issues.append(f"{stale_games} games not updating (API failure)")
                    details["stale_games"] = stale_games

                # NEW: Check MAXIMUS pregame pipeline is generating predictions
                # Conservative: only after 10:00 league time to avoid noisy alerts.
                try:
                    now_lt = league_now()
                    if now_lt.hour >= 10:
                        today = league_day_str()
                        scheduled_games = db.execute(text("""
                            SELECT COUNT(*) FROM games
                            WHERE DATE(game_date) = :today
                              AND game_status = 'Scheduled'
                        """), {"today": today}).fetchone()[0]

                        pregame_preds = (
                            db.query(Prediction)
                            .join(Game)
                            .filter(
                                Prediction.trigger_type == DBTriggerType.PREGAME,
                                Game.game_date >= datetime.strptime(today, "%Y-%m-%d"),
                                Game.game_date < (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=1)),
                            )
                            .count()
                        )

                        if scheduled_games > 0 and pregame_preds == 0:
                            issues.append("pregame predictions missing (MAXIMUS)")
                            details["scheduled_games"] = scheduled_games
                            details["pregame_predictions"] = pregame_preds
                except Exception as _e:
                    # Never fail the watchdog check because of a secondary check
                    pass

            finally:
                db.close()

            if issues:
                return ServiceStatus(
                    "Stuck States",
                    running=False,
                    message=", ".join(issues),
                    details=details,
                )
            else:
                return ServiceStatus(
                    "Stuck States",
                    running=True,
                    message="No issues",
                )

        except Exception as e:
            return ServiceStatus(
                "Stuck States",
                running=False,
                message=f"Check failed: {e}",
            )


    def _check_duplicate_processes(self) -> ServiceStatus:
        """Detect duplicate start.py or uvicorn processes that could cause double-posting."""
        try:
            # Find all start.py processes
            start_procs = []
            for proc in psutil.process_iter(['pid', 'cmdline', 'create_time']):
                cmdline = proc.info.get('cmdline') or []
                if any('start.py' in c for c in cmdline):
                    start_procs.append(proc.info)

            # Find uvicorn processes by port
            uvicorn_8000 = []
            uvicorn_8890 = []
            for proc in psutil.process_iter(['pid', 'cmdline', 'create_time']):
                cmdline = proc.info.get('cmdline') or []
                if not any('uvicorn' in c for c in cmdline):
                    continue
                if any('8000' == c or ':8000' in c for c in cmdline):
                    uvicorn_8000.append(proc.info)
                if any('8890' == c or ':8890' in c for c in cmdline):
                    uvicorn_8890.append(proc.info)

            issues = []
            details = {
                'start_py_count': len(start_procs),
                'uvicorn_8000_count': len(uvicorn_8000),
                'uvicorn_8890_count': len(uvicorn_8890),
            }

            if len(start_procs) > 1:
                issues.append(f"{len(start_procs)} automation instances")
            if len(uvicorn_8000) > 1:
                issues.append(f"{len(uvicorn_8000)} backend instances")
            if len(uvicorn_8890) > 1:
                issues.append(f"{len(uvicorn_8890)} odds instances")

            if issues:
                return ServiceStatus(
                    "Duplicate Processes",
                    running=False,
                    message=", ".join(issues),
                    details=details,
                )

            return ServiceStatus(
                "Duplicate Processes",
                running=True,
                message="None",
                details=details,
            )

        except Exception as e:
            return ServiceStatus(
                "Duplicate Processes",
                running=False,
                message=f"Check failed: {e}",
            )

    def _fix_duplicate_processes(self, service: ServiceStatus) -> bool:
        """Kill duplicate processes safely to prevent duplicate Discord posts."""
        try:
            killed = 0

            # Prefer keeping PID from PID file if valid
            keep_pid = None
            try:
                if PID_FILE.exists():
                    pid = int(PID_FILE.read_text().strip())
                    if self._is_process_running(pid):
                        keep_pid = pid
            except Exception:
                keep_pid = None

            # Kill extra start.py processes
            start_procs = []
            for proc in psutil.process_iter(['pid', 'cmdline', 'create_time']):
                cmdline = proc.info.get('cmdline') or []
                if any('start.py' in c for c in cmdline):
                    start_procs.append(proc.info)

            # If no keep_pid, keep the newest start.py
            if keep_pid is None and start_procs:
                newest = max(start_procs, key=lambda x: x.get('create_time') or 0)
                keep_pid = newest['pid']

            for info in start_procs:
                pid = info['pid']
                if pid == keep_pid:
                    continue
                logger.warning(f"Killing duplicate automation process PID {pid} (keeping {keep_pid})")
                try:
                    os.kill(pid, signal.SIGTERM)
                    time.sleep(2)
                    if self._is_process_running(pid):
                        os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass
                killed += 1

            # For uvicorn, keep the newest per port
            def kill_extras_for_port(port: int):
                nonlocal killed
                procs = []
                for proc in psutil.process_iter(['pid', 'cmdline', 'create_time']):
                    cmdline = proc.info.get('cmdline') or []
                    if not any('uvicorn' in c for c in cmdline):
                        continue
                    if any(str(port) == c or f":{port}" in c for c in cmdline):
                        procs.append(proc.info)
                if len(procs) <= 1:
                    return
                keep = max(procs, key=lambda x: x.get('create_time') or 0)
                for info in procs:
                    if info['pid'] == keep['pid']:
                        continue
                    logger.warning(f"Killing duplicate uvicorn for port {port}: PID {info['pid']} (keeping {keep['pid']})")
                    try:
                        os.kill(info['pid'], signal.SIGTERM)
                        time.sleep(1)
                        if self._is_process_running(info['pid']):
                            os.kill(info['pid'], signal.SIGKILL)
                    except Exception:
                        pass
                    killed += 1

            kill_extras_for_port(PORTS['backend'])
            kill_extras_for_port(PORTS['odds_api'])

            if killed > 0:
                self._send_alert(
                    f"⚠️ **Duplicate Process Cleanup**\nKilled {killed} duplicate process(es) to prevent double-posting.",
                    "Duplicate Processes",
                    force=True,
                )

            return True
        except Exception as e:
            logger.error(f"Failed to fix duplicates: {e}")
            return False

    def _log_status(self, services: List[ServiceStatus]):
        """Log status of all services."""
        all_healthy = all(s.running for s in services)

        for service in services:
            if service.running:
                logger.info(f"✅ {service.name}: {service.message}")
                if service.details:
                    logger.debug(f"   Details: {service.details}")
            else:
                logger.warning(f"❌ {service.name}: {service.message}")
                if service.details:
                    logger.warning(f"   Details: {service.details}")

        if all_healthy:
            logger.info("All systems healthy ✓")
        else:
            logger.warning("Some systems unhealthy - attempting fixes...")

    def _handle_failures(self, services: List[ServiceStatus]):
        """Handle failed services - restart if auto-restart enabled."""
        if not self.auto_restart:
            return

        for service in services:
            if not service.running:
                self._restart_service(service)

    def _restart_service(self, service: ServiceStatus):
        """Restart a failed service."""
        service_name = service.name

        # Check if we've restarted too many times recently
        if not self._can_restart(service_name):
            self._send_alert(
                f"🚨 **CRITICAL**: {service_name} failed too many times. Stopping auto-restart for this service.",
                service_name,
            )
            return

        # Check alert cooldown
        if self._is_alert_cooldown_active(service_name):
            logger.info(f"Alert cooldown active for {service_name}, skipping notification")
        else:
            self._send_alert(
                f"⚠️ **Service Down**: {service_name}\n\nMessage: {service.message}\n\nAttempting restart...",
                service_name,
            )

        # Attempt restart based on service type
        success = False
        if service_name == "Automation":
            success = self._restart_automation()
        elif service_name == "Backend API":
            success = self._restart_backend()
        elif service_name == "Odds API":
            success = self._restart_odds_api()
        elif service_name == "MAXIMUS":
            success = self._restart_maximus()
        elif service_name == "Market Tracking":
            success = self._restart_market_tracking()
        elif service_name == "Duplicate Processes":
            success = self._fix_duplicate_processes(service)
        elif service_name == "Stuck States":
            success = self._fix_stuck_states(service)

        if success:
            logger.info(f"✅ Successfully restarted/fixed {service_name}")
            self._record_restart(service_name)
        else:
            logger.error(f"❌ Failed to restart {service_name}")
            # Don't spam CRITICAL alerts for non-core services (e.g. Stuck States).
            # Respect cooldown unless this is a core service that truly means the system is down.
            force_alert = service_name in ("Automation", "Backend API", "Odds API", "MAXIMUS", "Market Tracking")
            self._send_alert(
                f"🚨 **CRITICAL**: Failed to restart {service_name}. Manual intervention required!",
                service_name,
                force=force_alert,
            )

    def _can_restart(self, service_name: str) -> bool:
        """Check if we can restart a service (not too many recent restarts)."""
        now = datetime.now()
        # Clean old restart history
        self._restart_history = [
            t for t in self._restart_history if now - t < self._restart_window
        ]
        # Check if we're under the limit
        return len(self._restart_history) < self._max_restarts

    def _is_alert_cooldown_active(self, service_name: str) -> bool:
        """Check if alert cooldown is active for a service."""
        if service_name not in self._last_alert_time:
            return False
        return datetime.now() - self._last_alert_time[service_name] < self._alert_cooldown

    def _record_restart(self, service_name: str):
        """Record a restart for rate limiting."""
        self._restart_history.append(datetime.now())
        self._restart_counts[service_name] = self._restart_counts.get(service_name, 0) + 1
        logger.info(f"Restart count for {service_name}: {self._restart_counts[service_name]}")

    def _restart_automation(self) -> bool:
        """Restart the main automation process."""
        try:
            # Kill existing process if running
            if PID_FILE.exists():
                pid = int(PID_FILE.read_text().strip())
                if self._is_process_running(pid):
                    logger.info(f"Killing existing automation process (PID {pid})...")
                    os.kill(pid, signal.SIGTERM)
                    time.sleep(5)
                    # Force kill if still running
                    if self._is_process_running(pid):
                        logger.info(f"Force killing automation process (PID {pid})...")
                        os.kill(pid, signal.SIGKILL)
                        time.sleep(2)

            # Start new process
            logger.info("Starting new automation process...")
            python_cmd = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
            subprocess.Popen(
                [python_cmd, str(AUTOMATION_SCRIPT)],
                cwd=str(Path.cwd()),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
            )
            time.sleep(10)  # Give it time to start

            # Verify it's running
            if PID_FILE.exists():
                pid = int(PID_FILE.read_text().strip())
                if self._is_process_running(pid):
                    logger.info(f"Automation started successfully (PID {pid})")
                    return True

            logger.error("Automation failed to start")
            return False
        except Exception as e:
            logger.error(f"Failed to restart automation: {e}")
            return False

    def _restart_backend(self) -> bool:
        """Restart the backend API (uvicorn on port 8000)."""
        try:
            port = PORTS["backend"]
            url = HEALTH_ENDPOINTS["backend"]

            # Kill any existing backend uvicorn on the port
            for proc in psutil.process_iter(['pid', 'cmdline']):
                cmdline = proc.info.get('cmdline') or []
                if any('uvicorn' in c for c in cmdline) and any(str(port) == c or f":{port}" in c for c in cmdline):
                    logger.info(f"Killing backend uvicorn (PID {proc.info['pid']})")
                    os.kill(proc.info['pid'], signal.SIGTERM)
                    time.sleep(2)

            log_path = Path('logs') / 'watchdog_backend_restart.log'
            log_fh = open(log_path, 'a', buffering=1)

            logger.info("Starting backend via uvicorn...")
            subprocess.Popen(
                [
                    (str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable),
                    '-m',
                    'uvicorn',
                    'dashboard.backend.main:app',
                    '--host',
                    '0.0.0.0',
                    '--port',
                    str(port),
                ],
                cwd=str(Path.cwd()),
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
            )

            # Wait for health
            for _ in range(20):
                try:
                    resp = requests.get(url, timeout=3)
                    if resp.status_code == 200:
                        return True
                except Exception:
                    pass
                time.sleep(1)

            return False
        except Exception as e:
            logger.error(f"Failed to restart backend: {e}")
            return False

    def _restart_odds_api(self) -> bool:
        """Restart the Odds API (uvicorn on port 8890)."""
        try:
            port = PORTS["odds_api"]
            url = HEALTH_ENDPOINTS["odds_api"]

            # Kill any existing odds uvicorn on the port
            for proc in psutil.process_iter(['pid', 'cmdline']):
                cmdline = proc.info.get('cmdline') or []
                if any('uvicorn' in c for c in cmdline) and any(str(port) == c or f":{port}" in c for c in cmdline):
                    logger.info(f"Killing odds uvicorn (PID {proc.info['pid']})")
                    os.kill(proc.info['pid'], signal.SIGTERM)
                    time.sleep(2)

            odds_dir = Path.cwd().parent / 'Odds_Api'
            venv_python = odds_dir / '.venv' / 'bin' / 'python'
            python_cmd = str(venv_python) if venv_python.exists() else sys.executable

            env = {**os.environ, 'ODDS_PROVIDER': 'composite', 'PORT': str(port)}

            log_path = Path('logs') / 'watchdog_odds_restart.log'
            log_fh = open(log_path, 'a', buffering=1)

            logger.info("Starting Odds API via uvicorn...")
            subprocess.Popen(
                [
                    python_cmd,
                    '-m',
                    'uvicorn',
                    'app.main:app',
                    '--host',
                    '0.0.0.0',
                    '--port',
                    str(port),
                ],
                cwd=str(odds_dir),
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=env,
            )

            # Wait for health
            for _ in range(40):
                try:
                    resp = requests.get(url, timeout=3)
                    if resp.status_code == 200:
                        return True
                except Exception:
                    pass
                time.sleep(1)

            return False
        except Exception as e:
            logger.error(f"Failed to restart Odds API: {e}")
            return False


    def _restart_maximus(self) -> bool:
        """Restart the MAXIMUS sidecar runner."""
        try:
            # Kill existing process from PID file
            if MAXIMUS_PID_FILE.exists():
                try:
                    pid = int(MAXIMUS_PID_FILE.read_text().strip())
                    if self._is_process_running(pid):
                        logger.info(f"Killing existing MAXIMUS process (PID {pid})...")
                        os.kill(pid, signal.SIGTERM)
                        time.sleep(2)
                        if self._is_process_running(pid):
                            os.kill(pid, signal.SIGKILL)
                            time.sleep(1)
                except Exception:
                    pass

            # Kill any stray maximus runners (safety)
            for proc in psutil.process_iter(['pid', 'cmdline']):
                cmdline = proc.info.get('cmdline') or []
                if any('run_maximus_pregame.py' in c for c in cmdline):
                    try:
                        logger.info(f"Killing stray MAXIMUS runner PID {proc.info['pid']}")
                        os.kill(int(proc.info['pid']), signal.SIGTERM)
                    except Exception:
                        pass

            # Start new process
            python_cmd = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
            log_path = Path('maximus.log')
            log_fh = open(log_path, 'a', buffering=1)

            logger.info("Starting MAXIMUS sidecar...")
            proc = subprocess.Popen(
                [python_cmd, str(MAXIMUS_SCRIPT)],
                cwd=str(Path.cwd()),
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
            )

            # Write PID file
            try:
                MAXIMUS_PID_FILE.write_text(str(proc.pid))
            except Exception:
                pass

            time.sleep(2)
            return self._is_process_running(proc.pid)
        except Exception as e:
            logger.error(f"Failed to restart MAXIMUS: {e}")
            return False


    def _restart_market_tracking(self) -> bool:
        """Restart the Market Tracking sidecar runner."""
        try:
            # Kill existing process from PID file
            if MARKET_TRACK_PID_FILE.exists():
                try:
                    pid = int(MARKET_TRACK_PID_FILE.read_text().strip())
                    if self._is_process_running(pid):
                        logger.info(f"Killing existing Market Tracking process (PID {pid})...")
                        os.kill(pid, signal.SIGTERM)
                        time.sleep(2)
                        if self._is_process_running(pid):
                            os.kill(pid, signal.SIGKILL)
                            time.sleep(1)
                except Exception:
                    pass

            # Kill stray runners
            for proc in psutil.process_iter(['pid', 'cmdline']):
                cmdline = proc.info.get('cmdline') or []
                if any('run_market_tracking.py' in c for c in cmdline):
                    try:
                        logger.info(f"Killing stray Market Tracking runner PID {proc.info['pid']}")
                        os.kill(int(proc.info['pid']), signal.SIGTERM)
                    except Exception:
                        pass

            python_cmd = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
            log_path = Path('market_tracking.log')
            log_fh = open(log_path, 'a', buffering=1)

            logger.info("Starting Market Tracking sidecar...")
            proc = subprocess.Popen(
                [python_cmd, str(MARKET_TRACK_SCRIPT)],
                cwd=str(Path.cwd()),
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
            )

            try:
                MARKET_TRACK_PID_FILE.write_text(str(proc.pid))
            except Exception:
                pass

            time.sleep(2)
            return self._is_process_running(proc.pid)
        except Exception as e:
            logger.error(f"Failed to restart Market Tracking: {e}")
            return False

    def _fix_stuck_states(self, service: ServiceStatus) -> bool:
        """Fix stuck states."""
        try:
            sys.path.insert(0, str(Path.cwd()))
            from dashboard.backend.database import SessionLocal, Prediction, PredictionStatus as DBPredictionStatus
            from src.utils.league_time import league_day_str
            from sqlalchemy import text
            import pandas as pd

            db = SessionLocal()
            fixed = 0
            issues_fixed = []

            try:
                # Fix stale predictions - mark them as failed
                four_hours_ago = datetime.now() - timedelta(hours=4)
                stale = db.query(Prediction).filter(
                    Prediction.created_at < four_hours_ago,
                    Prediction.posted_to_discord == False,
                    Prediction.status.in_(['PENDING', 'FAILED'])
                ).all()

                for pred in stale:
                    pred.status = DBPredictionStatus.FAILED
                    fixed += 1
                db.commit()
                if stale:
                    issues_fixed.append(f"Marked {len(stale)} stale predictions as FAILED")

                # Fix games wrong date - queue today's games
                # Only check games from today (not historical or future games)
                wrong_date = db.execute(text("""
                    SELECT COUNT(*) FROM games
                    WHERE DATE(game_date) = :today
                      AND game_status NOT IN ('Final', 'Scheduled')
                      AND updated_at < datetime('now', '-30 minutes')
                """), {"today": league_day_str()}).fetchone()[0]

                if wrong_date > 0:
                    # Trigger game re-queue by touching the schedule
                    from src.schedule import fetch_schedule
                    today = league_day_str()
                    schedule = fetch_schedule(today)
                    issues_fixed.append(f"Refreshed schedule for {len(schedule.get('games', []))} games")

            finally:
                db.close()

            if issues_fixed:
                logger.info(f"Fixed stuck states: {', '.join(issues_fixed)}")
                return True
            else:
                logger.warning("No stuck states to fix")
                return False
        except Exception as e:
            logger.error(f"Failed to fix stuck states: {e}")
            return False

    def _is_process_running(self, pid: int) -> bool:
        """Check if a process with given PID is running."""
        try:
            return psutil.pid_exists(pid)
        except Exception:
            return False

    def _send_alert(self, message: str, service_name: str, force: bool = False):
        """Send alert via Discord webhook."""
        try:
            webhook_url = os.environ.get("DISCORD_ALERTS_WEBHOOK")
            if not webhook_url:
                webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")

            if not webhook_url:
                logger.warning("No Discord webhook configured for alerts")
                return

            # Check cooldown
            if not force and self._is_alert_cooldown_active(service_name):
                return

            # Send alert
            response = requests.post(
                webhook_url,
                json={
                    "content": f"**WATCHDOG ALERT**\n\n{message}\n\n_Time: {datetime.now().strftime('%H:%M:%S')}_",
                },
                timeout=10,
            )

            if response.status_code == 204:
                self._last_alert_time[service_name] = datetime.now()
                logger.info(f"Alert sent for {service_name}")
            else:
                logger.warning(f"Failed to send alert: HTTP {response.status_code}")

        except Exception as e:
            logger.error(f"Failed to send alert: {e}")


def main():
    parser = argparse.ArgumentParser(description="PerryPicks Health Watchdog")
    parser.add_argument(
        "--check-interval",
        type=int,
        default=60,
        help="How often to check (seconds, default: 60)",
    )
    parser.add_argument(
        "--no-restart",
        action="store_true",
        help="Don't restart services, only alert (for debugging)",
    )
    args = parser.parse_args()

    # Check if already running
    if WATCHDOG_PID_FILE.exists():
        pid = int(WATCHDOG_PID_FILE.read_text().strip())
        if psutil.pid_exists(pid):
            logger.error(f"Watchdog already running (PID {pid})")
            logger.error("Run: kill -15 {pid} to stop existing watchdog")
            sys.exit(1)
        else:
            logger.warning("Removing stale watchdog PID file")
            WATCHDOG_PID_FILE.unlink()

    # Start watchdog
    watchdog = Watchdog(
        check_interval=args.check_interval,
        auto_restart=not args.no_restart,
    )
    watchdog.start()

if __name__ == "__main__":
    main()

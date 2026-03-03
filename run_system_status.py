"""System status dashboard - tracks all automation processes and posts daily status updates.

Similar to market tracking: creates one post per day and updates it throughout the day.
Shows visual indicators (🟢 green / 🔴 red) for each system's status.

Features:
- Daily post creation with cleanup
- Visual status indicators (running/down)
- Downtime calculation
- Last update timestamp in CST
- Automatic cleanup of old posts

Environment variables:
- DISCORD_SYSTEM_STATUS_WEBHOOK: Discord webhook for status posts

Run:
  .venv/bin/python run_system_status.py

Stop:
  kill <pid>
"""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv
from sqlalchemy.exc import OperationalError

# Ensure we import from THIS repo
REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from dashboard.backend.database import (
    SessionLocal,
    Base,
    Column,
    Integer,
    String,
    DateTime,
)
from src.automation.discord_client import DiscordClient

# Try to import SystemStatusMessage if it exists
try:
    from dashboard.backend.database import SystemStatusMessage
except ImportError:
    # Define it inline if not yet in database.py
    Base2 = Base
    SystemStatusMessage = None

logger = logging.getLogger("system-status")

HEARTBEAT_PATH = Path(".system_status.heartbeat")
PID_PATH = Path(".system_status.pid")

CST = ZoneInfo("America/Chicago")


@dataclass(frozen=True)
class SystemInfo:
    """Information about a system process."""
    name: str
    pid_file: str
    description: str


# Define all systems to monitor
SYSTEMS: List[SystemInfo] = [
    SystemInfo(
        name="Main Automation",
        pid_file=".perrypicks.pid",
        description="HALFTIME/Q3 predictions, live bet tracking, bet resolution"
    ),
    SystemInfo(
        name="Watchdog",
        pid_file=".watchdog.pid",
        description="System monitoring, auto-restart if processes crash"
    ),
    SystemInfo(
        name="MAXIMUS Pregame",
        pid_file=".maximus.pid",
        description="PREGAME predictions, game preview posts (1 hour before tip)"
    ),
    SystemInfo(
        name="Market Tracking",
        pid_file=".market_tracking.pid",
        description="Live bet tracking during Q3/Q4, bet progress updates"
    ),
]


@dataclass(frozen=True)
class RunnerConfig:
    poll_seconds: int = 60
    edit_seconds: int = 30
    daily_refresh_hour: int = 0  # Midnight CST for daily refresh


def get_process_status(pid_file: str, repo_root: Path) -> Tuple[bool, Optional[int], Optional[datetime]]:
    """Check if a process is running.
    
    Returns:
        (is_running, pid, start_time)
    """
    pid_path = repo_root / pid_file
    if not pid_path.exists():
        return False, None, None
    
    try:
        with open(pid_path, 'r') as f:
            pid_str = f.read().strip()
            pid = int(pid_str)
    except (ValueError, IOError):
        return False, None, None
    
    # Check if process is running
    try:
        os.kill(pid, 0)  # Signal 0 doesn't kill, just checks
    except OSError:
        return False, pid, None
    
    # Get process start time
    try:
        stat_path = Path(f"/proc/{pid}/stat")
        if stat_path.exists():
            with open(stat_path, 'r') as f:
                parts = f.read().split()
                # Start time is in jiffies, convert to seconds
                start_jiffies = int(parts[21])
                start_time = datetime.fromtimestamp(start_jiffies / 100.0, tz=timezone.utc)
                return True, pid, start_time
    except Exception:
        pass
    
    return True, pid, None


def format_duration(seconds: int) -> str:
    """Format duration in seconds to human-readable string."""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes}m"
    elif seconds < 86400:
        hours = seconds // 3600
        return f"{hours}h"
    else:
        days = seconds // 86400
        return f"{days}d"



def check_odds_api_health() -> Tuple[bool, Optional[str]]:
    """Check if the local Odds API is healthy.
    
    Returns:
        (is_healthy, error_message)
    """
    try:
        import requests
        response = requests.get("http://localhost:8890/v1/health", timeout=5)
        if response.status_code == 200:
            return True, None
        else:
            return False, f"HTTP {response.status_code}"
    except requests.exceptions.Timeout:
        return False, "Timeout"
    except requests.exceptions.ConnectionError:
        return False, "Connection refused"
    except Exception as e:
        return False, str(e)



def check_live_games_odds() -> List[Dict[str, str]]:
    """Check if odds can be fetched for in-progress games.
    
    Returns:
        List of dicts with game info and odds status:
        [{"away_tri": "GSW", "home_tri": "HOU", "status": "ok/failed", "error": None}]
    """
    try:
        from dashboard.backend.database import SessionLocal, Game
        import requests
        
        db = SessionLocal()
        
        # Get all active games from today (not Final)
        # This includes scheduled, Q1, Q2, Q3, Q4, in-progress
        from datetime import date
        today_cst = date.today()
        games = db.query(Game).filter(
            Game.game_date >= today_cst,
            Game.game_status != "Final",
        ).all()
        
        if not games:
            db.close()
            return []
        
        # Fetch all NBA odds from Odds API (single call for efficiency)
        try:
            response = requests.get("http://localhost:8890/v1/odds?sport=nba", timeout=5)
            if response.status_code != 200:
                db.close()
                return []
            
            all_odds = response.json()
            events = all_odds.get("events", [])
            
            # Create lookup by team tricode (home_tri, away_tri)
            odds_lookup = {}
            for event in events:
                home_tri = event.get("home_tricode", "").upper()
                away_tri = event.get("away_tricode", "").upper()
                if home_tri and away_tri:
                    key = (away_tri, home_tri)
                    odds_lookup[key] = event
            
        except Exception as e:
            logger.error(f"Failed to fetch odds from API: {e}")
            db.close()
            return []
        
        games_odds_status = []
        
        for game in games:
            # Try to find odds by team tricode
            key = (game.away_team, game.home_team)
            event = odds_lookup.get(key)
            
            if event:
                # Check if we have main odds types
                has_main_odds = False
                bookmakers = event.get("bookmakers", [])
                if bookmakers:
                    markets = bookmakers[0].get("markets", {})
                    has_moneyline = markets.get("moneyline") and (
                        markets["moneyline"].get("home") is not None or
                        markets["moneyline"].get("away") is not None
                    )
                    has_spread = markets.get("spread") and markets["spread"].get("line") is not None
                    has_total = markets.get("total") and markets["total"].get("line") is not None
                    
                    has_main_odds = has_moneyline or has_spread or has_total
                
                games_odds_status.append({
                    "away_tri": game.away_team,
                    "home_tri": game.home_team,
                    "status": "ok" if has_main_odds else "no_data",
                    "error": None,
                })
            else:
                games_odds_status.append({
                    "away_tri": game.away_team,
                    "home_tri": game.home_team,
                    "status": "failed",
                    "error": "No odds data",
                })
        
        db.close()
        return games_odds_status
        
    except Exception as e:
        # If database or other error, return empty list
        logger.error(f"Error checking live games odds: {e}")
        return []


def build_status_embed(
    systems_status: List[Dict],
    last_updated_cst: str,
    current_date_cst: str,
    live_games_odds: Optional[List[Dict]] = None
) -> Dict:
    """Build Discord embed for system status.
    
    Args:
        systems_status: List of system status dictionaries
        last_updated_cst: Last update timestamp in CST
        current_date_cst: Current calendar date in CST
    """
    status_lines = []
    running_count = 0
    
    for sys_info in systems_status:
        if sys_info["running"]:
            status_lines.append(f"🟢 **{sys_info['name']}** - Running")
            if sys_info.get("uptime"):
                status_lines.append(f"   ├─ Uptime: {sys_info['uptime']}")
            
            # Add live games odds verification for Odds API
            if sys_info['name'] == 'Odds API' and live_games_odds:
                status_lines.append(f"   ├─ Live Games Odds Check:")
                if len(live_games_odds) == 0:
                    status_lines.append(f"   │  └─ No games in progress")
                else:
                    for i, game_odds in enumerate(live_games_odds):
                        is_last = i == len(live_games_odds) - 1
                        game_str = f"{game_odds['away_tri']}@{game_odds['home_tri']}"
                        if game_odds['status'] == 'ok':
                            check = "✅"
                        elif game_odds['status'] == 'no_data':
                            check = "⚠️"  # Yellow triangle for no odds data
                        else:
                            check = "❌"
                        
                        prefix = "   │  └─" if is_last else "   │  ├─"
                        
                        if game_odds.get('error'):
                            status_lines.append(f"{prefix} {check} {game_str} ({game_odds['error']})")
                        else:
                            status_lines.append(f"{prefix} {check} {game_str}")
            
            running_count += 1
        else:
            status_lines.append(f"🔴 **{sys_info['name']}** - DOWN")
            if sys_info.get("downtime"):
                status_lines.append(f"   ├─ Down for: {sys_info['downtime']}")
            status_lines.append(f"   ├─ {sys_info['description']}")
            if sys_info.get("error"):
                status_lines.append(f"   ├─ Error: {sys_info['error']}")
    
    status_lines.append("")
    status_lines.append(f"**Summary:** {running_count}/{len(systems_status)} systems running")
    status_lines.append(f"**Last Updated:** {last_updated_cst}")
    status_lines.append(f"**Date:** {current_date_cst}")
    
    embed = {
        "title": "🖥️ PerryPicks System Status",
        "description": "\n".join(status_lines),
        "color": 0x00ff00 if running_count == len(systems_status) else 0xff0000,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {
            "text": "System Status Dashboard • Auto-updates every 30 seconds"
        }
    }
    
    return embed


def get_or_create_status_message(
    db,
    current_date_cst: datetime,
    discord_client: DiscordClient
) -> Optional[Tuple[str, bool]]:
    """Get existing active status message or create new one.
    
    Returns:
        (discord_message_id, is_new) or (None, False) if failed
    """
    if SystemStatusMessage is None:
        logger.warning("SystemStatusMessage table not available - using in-memory tracking")
        return None, False
    
    # Archive old messages and find/create new one
    now_utc = datetime.now(timezone.utc)
    
    # Archive old messages
    db.query(SystemStatusMessage).filter(
        SystemStatusMessage.date < current_date_cst.date(),
        SystemStatusMessage.status == "active"
    ).update({"status": "archived"})
    db.commit()
    
    # Look for active message for today
    msg = db.query(SystemStatusMessage).filter(
        SystemStatusMessage.date == current_date_cst.date(),
        SystemStatusMessage.status == "active"
    ).first()
    
    if msg:
        return msg.discord_message_id, False
    
    # Create new message
    logger.info("Creating new system status message for today")
    result = discord_client.post_message("", embeds=[build_status_embed(
        [], 
        datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
        current_date_cst.strftime("%Y-%m-%d")
    )], wait=True)
    
    if not result.success:
        logger.error(f"Failed to create status message: {result.error}")
        return None, False
    
    msg = SystemStatusMessage(
        discord_message_id=result.message_id,
        date=current_date_cst.date(),
        status="active",
        last_updated_at=now_utc,
        last_updated_cst=datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    )
    db.add(msg)
    db.commit()
    
    return result.message_id, True


def update_status_message(
    db,
    discord_message_id: str,
    systems_status: List[Dict],
    last_updated_cst: str,
    current_date_cst: str,
    discord_client: DiscordClient,
    live_games_odds: Optional[List[Dict]] = None
) -> bool:
    """Update the Discord status message."""
    embed = build_status_embed(systems_status, last_updated_cst, current_date_cst, live_games_odds)
    result = discord_client.edit_message(message_id=discord_message_id, content="", embeds=[embed])
    
    if result.success:
        # Update database
        if SystemStatusMessage is not None:
            msg = db.query(SystemStatusMessage).filter(
                SystemStatusMessage.discord_message_id == discord_message_id
            ).first()
            if msg:
                msg.last_updated_at = datetime.now(timezone.utc)
                msg.last_updated_cst = last_updated_cst
                msg.consecutive_edit_failures = 0
                msg.last_error = None
                db.commit()
        return True
    else:
        logger.error(f"Failed to update status message: {result.error}")
        if SystemStatusMessage is not None:
            msg = db.query(SystemStatusMessage).filter(
                SystemStatusMessage.discord_message_id == discord_message_id
            ).first()
            if msg:
                msg.consecutive_edit_failures += 1
                msg.last_error = result.error
                db.commit()
        return False


def main_loop(config: RunnerConfig, repo_root: Path) -> None:
    """Main monitoring loop."""
    load_dotenv()
    
    # Get Discord webhook
    webhook_url = os.environ.get("DISCORD_SYSTEM_STATUS_WEBHOOK") or \
                  os.environ.get("DISCORD_ALERTS_WEBHOOK")
    
    if not webhook_url:
        logger.error("DISCORD_SYSTEM_STATUS_WEBHOOK environment variable required")
        return
    
    discord_client = DiscordClient(webhook_url=webhook_url)
    
    logger.info("System status dashboard starting")
    logger.info(f"Polling every {config.poll_seconds}s, updating every {config.edit_seconds}s")
    
    last_edit_time = datetime.min.replace(tzinfo=timezone.utc)
    discord_message_id = None
    
    # Initialize database
    try:
        db = SessionLocal()
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        return
    
    try:
        while True:
            # Write heartbeat
            HEARTBEAT_PATH.write_text(datetime.now(timezone.utc).isoformat())
            
            # Get current time in CST
            now_cst = datetime.now(CST)
            now_utc = datetime.now(timezone.utc)
            
            # Check if we need a new daily post
            is_new_day = (discord_message_id is None or 
                          (now_cst.hour == 0 and now_cst.minute < 5))
            
            if is_new_day or discord_message_id is None:
                discord_message_id, is_new = get_or_create_status_message(
                    db, now_cst, discord_client
                )
                if is_new:
                    logger.info(f"Created new status message: {discord_message_id}")
                last_edit_time = now_utc - timedelta(seconds=config.edit_seconds)
            
            # Check if it's time to update
            time_since_edit = (now_utc - last_edit_time).total_seconds()
            
            if time_since_edit >= config.edit_seconds and discord_message_id:
                # Gather system status
                systems_status = []
                for sys_info in SYSTEMS:
                    is_running, pid, start_time = get_process_status(
                        sys_info.pid_file, repo_root
                    )
                    
                    sys_status = {
                        "name": sys_info.name,
                        "running": is_running,
                        "description": sys_info.description,
                    }
                    
                    if is_running and start_time:
                        uptime_seconds = int((now_utc - start_time).total_seconds())
                        sys_status["uptime"] = format_duration(uptime_seconds)
                    elif not is_running:
                        # Estimate downtime from PID file modification time
                        pid_path = repo_root / sys_info.pid_file
                        if pid_path.exists():
                            mtime = datetime.fromtimestamp(pid_path.stat().st_mtime, tz=timezone.utc)
                            downtime_seconds = int((now_utc - mtime).total_seconds())
                            sys_status["downtime"] = format_duration(downtime_seconds)
                    
                    systems_status.append(sys_status)
                
                # Check Odds API status
                odds_healthy, odds_error = check_odds_api_health()
                systems_status.append({
                    "name": "Odds API",
                    "running": odds_healthy,
                    "description": "Local odds provider for game odds (port 8890)",
                    "error": odds_error if not odds_healthy else None,
                })
                
                # Check odds for live games
                live_games_odds = []
                if odds_healthy:
                    live_games_odds = check_live_games_odds()
                
                # Update the message
                success = update_status_message(
                    db,
                    discord_message_id,
                    systems_status,
                    now_cst.strftime("%Y-%m-%d %H:%M:%S CST"),
                    now_cst.strftime("%Y-%m-%d"),
                    discord_client,
                    live_games_odds
                )
                
                if success:
                    last_edit_time = now_utc
                    logger.info("Updated system status message")
                else:
                    logger.warning("Failed to update status message")
            
            # Sleep
            time.sleep(config.poll_seconds)
            
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.exception(f"Error in main loop: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Write PID
    PID_PATH.write_text(str(os.getpid()))
    
    # Run
    REPO_ROOT = Path(__file__).resolve().parent
    config = RunnerConfig()
    
    try:
        main_loop(config, REPO_ROOT)
    finally:
        PID_PATH.unlink(missing_ok=True)
        HEARTBEAT_PATH.unlink(missing_ok=True)

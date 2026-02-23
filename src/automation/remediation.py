"""
PerryPicks Alert System and Remediation Manager

Handles alert generation, routing to Discord, and remediation actions
that can be triggered remotely.

Alert Levels:
- CRITICAL: Immediate attention needed
- HIGH: Important issues affecting predictions
- MEDIUM: Issues with workarounds in place
- INFO: Status updates

Remediation Actions:
- refresh_temporal_data: Reload temporal feature store
- clear_cache: Clear NBA CDN cache
- reload_model: Reload REPTAR model
- restart_odds_api: Restart the local Odds API
- run_data_backfill: Backfill missing historical data

Usage:
    from src.automation.remediation import AlertManager, RemediationManager

    alert_manager = AlertManager(discord_client=client)
    alert_manager.critical("Service Shutdown", "PerryPicks stopped")

    remedy = RemediationManager()
    remedy.execute("refresh_temporal_data")
"""

import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    """Alert severity levels."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    INFO = "INFO"


@dataclass
class Alert:
    """Represents a single alert."""
    level: AlertLevel
    title: str
    message: str
    timestamp: datetime
    remedy_action: Optional[str] = None  # Suggested remedy action
    remedy_available: bool = False


class AlertManager:
    """
    Manages alert generation and Discord posting.

    All alerts are logged and optionally posted to Discord.
    """

    # Emoji prefixes for alert levels
    LEVEL_EMOJI = {
        AlertLevel.CRITICAL: "🚨",
        AlertLevel.HIGH: "⚠️",
        AlertLevel.MEDIUM: "⚡",
        AlertLevel.INFO: "ℹ️",
    }

    def __init__(self, discord_client=None, alerts_webhook_url: Optional[str] = None):
        """
        Initialize alert manager.

        Args:
            discord_client: DiscordClient instance for posting
            alerts_webhook_url: Direct webhook URL for alerts channel
        """
        self._discord_client = discord_client
        self._alerts_webhook_url = alerts_webhook_url
        self._alert_history: List[Alert] = []
        self._max_history = 100

    def _post_to_discord(self, content: str) -> bool:
        """Post alert to Discord alerts channel."""
        try:
            if self._alerts_webhook_url:
                import requests
                resp = requests.post(
                    self._alerts_webhook_url,
                    json={"content": content},
                    timeout=10
                )
                return resp.status_code in (200, 204)
            elif self._discord_client:
                result = self._discord_client.post_message(content)
                return result.success
        except Exception as e:
            logger.error(f"Failed to post alert to Discord: {e}")
            return False
        return False

    def _format_alert(self, alert: Alert) -> str:
        """Format alert for Discord."""
        emoji = self.LEVEL_EMOJI.get(alert.level, "📢")
        lines = [
            f"{emoji} **[{alert.level.value}] {alert.title}**",
            f"> {alert.message}",
            f"`{alert.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}`",
        ]

        if alert.remedy_available:
            lines.append(f"🔧 Remedy: `{alert.remedy_action}`")

        return "\n".join(lines)

    def _create_alert(
        self,
        level: AlertLevel,
        title: str,
        message: str,
        remedy_action: Optional[str] = None,
        post_to_discord: bool = True,
    ) -> Alert:
        """Create and optionally post an alert."""
        alert = Alert(
            level=level,
            title=title,
            message=message,
            timestamp=datetime.utcnow(),
            remedy_action=remedy_action,
            remedy_available=remedy_action is not None,
        )

        # Add to history
        self._alert_history.append(alert)
        if len(self._alert_history) > self._max_history:
            self._alert_history = self._alert_history[-self._max_history:]

        # Log the alert
        log_msg = f"[{level.value}] {title}: {message}"
        if level == AlertLevel.CRITICAL:
            logger.critical(log_msg)
        elif level == AlertLevel.HIGH:
            logger.error(log_msg)
        elif level == AlertLevel.MEDIUM:
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

        # Post to Discord if enabled
        if post_to_discord:
            content = self._format_alert(alert)
            self._post_to_discord(content)

        return alert

    # Convenience methods for each alert level

    def critical(self, title: str, message: str, remedy: Optional[str] = None) -> Alert:
        """Post a CRITICAL alert."""
        return self._create_alert(AlertLevel.CRITICAL, title, message, remedy)

    def high(self, title: str, message: str, remedy: Optional[str] = None) -> Alert:
        """Post a HIGH priority alert."""
        return self._create_alert(AlertLevel.HIGH, title, message, remedy)

    def medium(self, title: str, message: str, remedy: Optional[str] = None) -> Alert:
        """Post a MEDIUM priority alert."""
        return self._create_alert(AlertLevel.MEDIUM, title, message, remedy)

    def info(self, title: str, message: str, remedy: Optional[str] = None) -> Alert:
        """Post an INFO alert."""
        return self._create_alert(AlertLevel.INFO, title, message, remedy)

    # Pre-defined alerts for common scenarios

    def service_started(self) -> Alert:
        """Alert: Service started."""
        return self.info(
            "Service Started",
            "PerryPicks automation service is now running",
        )

    def service_shutdown(self, reason: str = "Normal shutdown") -> Alert:
        """Alert: Service shutdown."""
        return self.critical(
            "Service Shutdown",
            f"PerryPicks stopped: {reason}",
        )

    def model_load_failed(self, error: str) -> Alert:
        """Alert: Model failed to load."""
        return self.critical(
            "Model Load Failure",
            f"REPTAR model failed to load: {error}",
            remedy="reload_model"
        )

    def database_failure(self, error: str) -> Alert:
        """Alert: Database connection failed."""
        return self.critical(
            "Database Failure",
            f"Database connection failed: {error}",
        )

    def discord_post_failed(self, game_id: str, error: str) -> Alert:
        """Alert: Discord posting failed after retries."""
        return self.critical(
            "Discord Post Failed",
            f"Failed to post prediction for {game_id}: {error}",
        )

    def odds_api_down(self, local_failed: bool, external_failed: bool) -> Alert:
        """Alert: All odds sources unavailable."""
        return self.critical(
            "Odds API Down",
            f"Local: {'FAILED' if local_failed else 'OK'}, External: {'FAILED' if external_failed else 'OK'}",
            remedy="restart_odds_api"
        )

    def stale_temporal_data(self, days_stale: int) -> Alert:
        """Alert: Temporal data is stale."""
        return self.high(
            "Stale Temporal Data",
            f"Feature store is {days_stale} days old. Predictions may be less accurate.",
            remedy="refresh_temporal_data"
        )

    def nba_cdn_timeout(self, consecutive_failures: int) -> Alert:
        """Alert: Multiple NBA CDN timeouts."""
        return self.high(
            "NBA CDN Timeout",
            f"{consecutive_failures} consecutive timeouts fetching game data",
            remedy="clear_cache"
        )

    def halftime_detection_failed(self, game_id: str) -> Alert:
        """Alert: Couldn't detect halftime."""
        return self.high(
            "Halftime Detection Failed",
            f"Could not determine if game {game_id} is at halftime",
        )

    def prediction_failed(self, game_id: str, error: str) -> Alert:
        """Alert: Prediction generation failed."""
        return self.high(
            "Prediction Failed",
            f"Failed to generate prediction for {game_id}: {error}",
        )

    def no_games_found(self, date: str) -> Alert:
        """Alert: No games found for today."""
        return self.high(
            "No Games Found",
            f"Schedule fetch returned no games for {date}",
        )

    def odds_fetch_failed(self, source: str, fallback_used: str) -> Alert:
        """Alert: Odds fetch failed but fallback available."""
        return self.medium(
            "Odds Fetch Failed",
            f"{source} unavailable, using {fallback_used} fallback",
        )

    def cache_corrupted(self, cache_file: str) -> Alert:
        """Alert: Corrupt cache file detected."""
        return self.medium(
            "Cache Corrupted",
            f"Corrupt cache file deleted: {cache_file}",
            remedy="clear_cache"
        )

    def feature_validation_warning(self, issues: List[str]) -> Alert:
        """Alert: Feature validation issues."""
        return self.medium(
            "Feature Validation Issues",
            f"Issues: {', '.join(issues[:3])}",
        )

    def high_memory_usage(self, mb_used: int) -> Alert:
        """Alert: High memory usage."""
        return self.medium(
            "High Memory Usage",
            f"Process using {mb_used}MB RAM",
        )

    def schedule_refreshed(self, date: str, game_count: int) -> Alert:
        """Alert: Schedule refreshed."""
        return self.info(
            "Schedule Loaded",
            f"{game_count} games found for {date}",
        )

    def temporal_data_refreshed(self, games_added: int) -> Alert:
        """Alert: Temporal data refreshed."""
        return self.info(
            "Temporal Data Refreshed",
            f"Added {games_added} new games to feature store",
        )

    def odds_api_health_failed(self) -> Alert:
        """Alert: Local odds API health check failed."""
        return self.info(
            "Odds API Health Check Failed",
            "Local API not responding, using external API",
            remedy="restart_odds_api"
        )

    def get_recent_alerts(self, count: int = 10) -> List[Alert]:
        """Get recent alerts."""
        return self._alert_history[-count:]


class RemediationManager:
    """
    Manages remediation actions that can be triggered remotely.

    Actions can be triggered via:
    - HTTP API: POST /admin/remedy/<action>
    - Direct call: remedy.execute("action_name")
    """

    def __init__(self, project_root: Optional[str] = None):
        """
        Initialize remediation manager.

        Args:
            project_root: Path to PerryPicks project root
        """
        self.project_root = project_root or os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        self._actions: Dict[str, Callable] = {}
        self._register_default_actions()

    def _register_default_actions(self):
        """Register default remediation actions."""
        self._actions = {
            "refresh_temporal_data": self._refresh_temporal_data,
            "clear_cache": self._clear_cache,
            "reload_model": self._reload_model,
            "restart_odds_api": self._restart_odds_api,
            "run_data_backfill": self._run_data_backfill,
            "health_check": self._health_check,
            "get_status": self._get_status,
        }

    def register_action(self, name: str, func: Callable):
        """Register a custom remediation action."""
        self._actions[name] = func

    def list_actions(self) -> List[str]:
        """List available remediation actions."""
        return list(self._actions.keys())

    def execute(self, action_name: str, **kwargs) -> Dict:
        """
        Execute a remediation action.

        Args:
            action_name: Name of the action to execute
            **kwargs: Additional arguments for the action

        Returns:
            Dict with 'success', 'message', and 'details' keys
        """
        if action_name not in self._actions:
            return {
                "success": False,
                "message": f"Unknown action: {action_name}",
                "available_actions": self.list_actions(),
            }

        try:
            logger.info(f"Executing remediation action: {action_name}")
            result = self._actions[action_name](**kwargs)

            if result is None:
                result = {"success": True, "message": f"Action {action_name} completed"}

            logger.info(f"Remediation action {action_name} result: {result}")
            return result

        except Exception as e:
            logger.error(f"Remediation action {action_name} failed: {e}")
            return {
                "success": False,
                "message": f"Action failed: {str(e)}",
            }

    # Default remediation actions

    def _refresh_temporal_data(self) -> Dict:
        """Refresh temporal feature store with recent games."""
        try:
            from src.data.refresh_temporal import refresh_temporal_store

            games_added = refresh_temporal_store(days=30)

            return {
                "success": True,
                "message": f"Temporal data refreshed, {games_added} games added",
                "games_added": games_added,
            }
        except Exception as e:
            return {"success": False, "message": str(e)}

    def _clear_cache(self) -> Dict:
        """Clear NBA CDN cache directory."""
        try:
            import shutil
            from pathlib import Path

            cache_dir = Path(self.project_root) / ".cache" / "nba_cdn"

            if cache_dir.exists():
                file_count = len(list(cache_dir.glob("*.json")))
                shutil.rmtree(cache_dir)
                cache_dir.mkdir(parents=True, exist_ok=True)

                return {
                    "success": True,
                    "message": f"Cleared {file_count} cached files",
                    "files_cleared": file_count,
                }
            else:
                return {"success": True, "message": "No cache to clear"}

        except Exception as e:
            return {"success": False, "message": str(e)}

    def _reload_model(self) -> Dict:
        """Force reload of REPTAR model."""
        try:
            from src.models.reptar_predictor import get_predictor
            import importlib
            import src.models.reptar_predictor as module

            # Force module reload
            importlib.reload(module)

            # Get fresh predictor
            predictor = module.get_predictor()

            if predictor and predictor.is_loaded:
                return {
                    "success": True,
                    "message": "REPTAR model reloaded successfully",
                }
            else:
                return {"success": False, "message": "Model failed to load"}

        except Exception as e:
            return {"success": False, "message": str(e)}

    def _restart_odds_api(self) -> Dict:
        """Restart the local Odds API server."""
        try:
            # Kill existing process on port 8890
            subprocess.run(
                ["lsof", "-ti:8890", "|", "xargs", "kill", "-9"],
                shell=True,
                capture_output=True,
            )
            time.sleep(2)

            # Start new process
            odds_api_dir = Path(self.project_root).parent / "Odds_Api"
            odds_api_main = odds_api_dir / "app" / "main.py"

            if not odds_api_main.exists():
                return {"success": False, "message": "Odds API not found"}

            venv_python = odds_api_dir / ".venv" / "bin" / "python"
            python_cmd = str(venv_python) if venv_python.exists() else sys.executable

            env = {**os.environ, "ODDS_PROVIDER": "composite", "PORT": "8890"}

            subprocess.Popen(
                [python_cmd, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8890"],
                cwd=str(odds_api_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )

            # Wait for startup
            time.sleep(5)

            # Verify it's running
            import requests
            resp = requests.get("http://localhost:8890/v1/health", timeout=5)

            if resp.status_code == 200:
                return {"success": True, "message": "Odds API restarted on port 8890"}
            else:
                return {"success": False, "message": "Odds API started but health check failed"}

        except Exception as e:
            return {"success": False, "message": str(e)}

    def _run_data_backfill(self) -> Dict:
        """Backfill missing historical data."""
        try:
            # Run the backfill script
            result = subprocess.run(
                [sys.executable, "-m", "src.data.refresh_temporal", "--days", "7"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=300,
            )

            return {
                "success": result.returncode == 0,
                "message": "Data backfill completed" if result.returncode == 0 else "Backfill failed",
                "output": result.stdout[-500:] if result.stdout else "",
            }

        except Exception as e:
            return {"success": False, "message": str(e)}

    def _health_check(self) -> Dict:
        """Run comprehensive health check."""
        checks = {}

        # Check REPTAR model
        try:
            from src.models.reptar_predictor import get_predictor
            predictor = get_predictor()
            checks["reptar_model"] = predictor.is_loaded if predictor else False
        except:
            checks["reptar_model"] = False

        # Check database
        try:
            from src.db.models import SessionLocal
            db = SessionLocal()
            db.execute("SELECT 1")
            db.close()
            checks["database"] = True
        except:
            checks["database"] = False

        # Check Odds API
        try:
            import requests
            if os.environ.get("USE_LOCAL_ODDS_API", "").lower() == "true":
                resp = requests.get("http://localhost:8890/v1/health", timeout=5)
                checks["odds_api"] = resp.status_code == 200
            else:
                checks["odds_api"] = "external"
        except:
            checks["odds_api"] = False

        # Check temporal data
        try:
            from pathlib import Path
            data_path = Path(self.project_root) / "data" / "processed" / "halftime_with_refined_temporal.parquet"
            if data_path.exists():
                import pandas as pd
                df = pd.read_parquet(data_path)
                checks["temporal_data_rows"] = len(df)
            else:
                checks["temporal_data_rows"] = 0
        except:
            checks["temporal_data_rows"] = 0

        all_healthy = all(v in (True, "external") or (isinstance(v, int) and v > 0) for v in checks.values())

        return {
            "success": all_healthy,
            "message": "All systems healthy" if all_healthy else "Some issues detected",
            "checks": checks,
        }

    def _get_status(self) -> Dict:
        """Get current system status."""
        try:
            health = self._health_check()

            # Get recent alert count
            from src.automation.alert_manager import get_alert_manager
            alert_manager = get_alert_manager()
            recent_alerts = len(alert_manager.get_recent_alerts(50))

            return {
                "success": True,
                "message": "Status retrieved",
                "health": health.get("checks", {}),
                "recent_alerts": recent_alerts,
                "project_root": str(self.project_root),
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            return {"success": False, "message": str(e)}


# Global instances
_alert_manager: Optional[AlertManager] = None
_remediation_manager: Optional[RemediationManager] = None


def get_alert_manager() -> AlertManager:
    """Get or create the global alert manager."""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager()
    return _alert_manager


def get_remediation_manager() -> RemediationManager:
    """Get or create the global remediation manager."""
    global _remediation_manager
    if _remediation_manager is None:
        _remediation_manager = RemediationManager()
    return _remediation_manager


def init_alert_system(discord_client=None, alerts_webhook_url: Optional[str] = None):
    """Initialize the global alert system."""
    global _alert_manager
    _alert_manager = AlertManager(
        discord_client=discord_client,
        alerts_webhook_url=alerts_webhook_url,
    )
    return _alert_manager


__all__ = [
    "AlertManager",
    "RemediationManager",
    "AlertLevel",
    "Alert",
    "get_alert_manager",
    "get_remediation_manager",
    "init_alert_system",
]

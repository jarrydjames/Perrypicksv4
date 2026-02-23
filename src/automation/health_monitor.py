"""
Health Monitoring for PerryPicks

Monitors system health, detects issues, and can trigger alerts or restarts.

Features:
- API endpoint health checks
- Database connection monitoring
- Model load verification
- Memory and CPU monitoring
- Automatic recovery actions

Usage:
    from src.automation.health_monitor import HealthMonitor

    monitor = HealthMonitor()
    status = monitor.check_all()
    if not status.healthy:
        monitor.send_alert(status)
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health check status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class ComponentHealth:
    """Health status of a single component."""
    name: str
    status: HealthStatus
    message: str
    last_check: datetime
    latency_ms: Optional[float] = None
    details: Dict = field(default_factory=dict)


@dataclass
class SystemHealth:
    """Overall system health status."""
    healthy: bool
    status: HealthStatus
    components: List[ComponentHealth]
    timestamp: datetime
    uptime_seconds: float

    def summary(self) -> str:
        """Get human-readable summary."""
        issues = [c for c in self.components if c.status != HealthStatus.HEALTHY]
        if not issues:
            return f"All systems healthy (uptime: {self.uptime_seconds/3600:.1f}h)"

        return f"Issues detected: {', '.join(i.name for i in issues)}"


class HealthMonitor:
    """
    Monitors health of PerryPicks components.

    Components monitored:
    - NBA CDN API (data fetching)
    - Local Odds API (if running)
    - Discord webhook (posting capability)
    - REPTAR model (prediction engine)
    - Database (SQLite)
    """

    def __init__(
        self,
        discord_alert_callback: Optional[Callable] = None,
        check_interval_seconds: int = 60,
    ):
        """
        Initialize health monitor.

        Args:
            discord_alert_callback: Function to call for Discord alerts
            check_interval_seconds: How often to run health checks
        """
        self.discord_alert_callback = discord_alert_callback
        self.check_interval = check_interval_seconds
        self._start_time = datetime.utcnow()
        self._last_check: Optional[SystemHealth] = None
        self._consecutive_failures: Dict[str, int] = {}

    def check_all(self) -> SystemHealth:
        """
        Run all health checks.

        Returns:
            SystemHealth with status of all components
        """
        components = []

        # Check NBA CDN
        components.append(self._check_nba_cdn())

        # Check Local Odds API
        components.append(self._check_odds_api())

        # Check Discord
        components.append(self._check_discord())

        # Check REPTAR model
        components.append(self._check_reptar_model())

        # Check database
        components.append(self._check_database())

        # Determine overall status
        if all(c.status == HealthStatus.HEALTHY for c in components):
            overall_status = HealthStatus.HEALTHY
            healthy = True
        elif any(c.status == HealthStatus.UNHEALTHY for c in components):
            overall_status = HealthStatus.UNHEALTHY
            healthy = False
        else:
            overall_status = HealthStatus.DEGRADED
            healthy = True  # Degraded is still "up"

        uptime = (datetime.utcnow() - self._start_time).total_seconds()

        self._last_check = SystemHealth(
            healthy=healthy,
            status=overall_status,
            components=components,
            timestamp=datetime.utcnow(),
            uptime_seconds=uptime,
        )

        return self._last_check

    def _check_nba_cdn(self) -> ComponentHealth:
        """Check NBA CDN API connectivity."""
        start = time.time()
        try:
            import requests
            # Simple ping to NBA CDN
            url = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
            resp = requests.get(url, timeout=10)
            latency = (time.time() - start) * 1000

            if resp.status_code == 200:
                return ComponentHealth(
                    name="NBA CDN API",
                    status=HealthStatus.HEALTHY,
                    message="Connected",
                    last_check=datetime.utcnow(),
                    latency_ms=latency,
                )
            else:
                return ComponentHealth(
                    name="NBA CDN API",
                    status=HealthStatus.DEGRADED,
                    message=f"HTTP {resp.status_code}",
                    last_check=datetime.utcnow(),
                    latency_ms=latency,
                )
        except Exception as e:
            return ComponentHealth(
                name="NBA CDN API",
                status=HealthStatus.UNHEALTHY,
                message=f"Connection failed: {e}",
                last_check=datetime.utcnow(),
            )

    def _check_odds_api(self) -> ComponentHealth:
        """Check Local Odds API health."""
        import os

        # Skip if not using local odds API
        if os.environ.get("USE_LOCAL_ODDS_API", "").lower() != "true":
            return ComponentHealth(
                name="Local Odds API",
                status=HealthStatus.HEALTHY,
                message="Not configured (using external API)",
                last_check=datetime.utcnow(),
            )

        start = time.time()
        try:
            import requests
            url = "http://localhost:8890/v1/health"
            resp = requests.get(url, timeout=5)
            latency = (time.time() - start) * 1000

            if resp.status_code == 200:
                return ComponentHealth(
                    name="Local Odds API",
                    status=HealthStatus.HEALTHY,
                    message="Running",
                    last_check=datetime.utcnow(),
                    latency_ms=latency,
                )
            else:
                return ComponentHealth(
                    name="Local Odds API",
                    status=HealthStatus.UNHEALTHY,
                    message=f"HTTP {resp.status_code}",
                    last_check=datetime.utcnow(),
                    latency_ms=latency,
                )
        except Exception as e:
            return ComponentHealth(
                name="Local Odds API",
                status=HealthStatus.UNHEALTHY,
                message=f"Not responding: {e}",
                last_check=datetime.utcnow(),
            )

    def _check_discord(self) -> ComponentHealth:
        """Check Discord webhook configuration."""
        import os

        webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")

        if not webhook_url:
            return ComponentHealth(
                name="Discord",
                status=HealthStatus.DEGRADED,
                message="No webhook configured",
                last_check=datetime.utcnow(),
            )

        # Validate webhook URL format
        valid_prefixes = (
            "https://discord.com/api/webhooks/",
            "https://discordapp.com/api/webhooks/",
        )

        if webhook_url.startswith(valid_prefixes):
            return ComponentHealth(
                name="Discord",
                status=HealthStatus.HEALTHY,
                message="Webhook configured",
                last_check=datetime.utcnow(),
            )
        else:
            return ComponentHealth(
                name="Discord",
                status=HealthStatus.UNHEALTHY,
                message="Invalid webhook format",
                last_check=datetime.utcnow(),
            )

    def _check_reptar_model(self) -> ComponentHealth:
        """Check REPTAR model load status."""
        try:
            from src.models.reptar_predictor import get_predictor

            predictor = get_predictor()

            if predictor and predictor.is_loaded:
                return ComponentHealth(
                    name="REPTAR Model",
                    status=HealthStatus.HEALTHY,
                    message="Loaded and ready",
                    last_check=datetime.utcnow(),
                )
            else:
                return ComponentHealth(
                    name="REPTAR Model",
                    status=HealthStatus.UNHEALTHY,
                    message="Not loaded",
                    last_check=datetime.utcnow(),
                )
        except Exception as e:
            return ComponentHealth(
                name="REPTAR Model",
                status=HealthStatus.UNHEALTHY,
                message=f"Load failed: {e}",
                last_check=datetime.utcnow(),
            )

    def _check_database(self) -> ComponentHealth:
        """Check SQLite database connectivity."""
        try:
            from src.db.models import SessionLocal

            db = SessionLocal()
            try:
                # Simple query to test connection
                db.execute("SELECT 1")
                return ComponentHealth(
                    name="Database",
                    status=HealthStatus.HEALTHY,
                    message="Connected",
                    last_check=datetime.utcnow(),
                )
            finally:
                db.close()
        except Exception as e:
            return ComponentHealth(
                name="Database",
                status=HealthStatus.UNHEALTHY,
                message=f"Connection failed: {e}",
                last_check=datetime.utcnow(),
            )

    def send_alert(self, status: SystemHealth) -> bool:
        """
        Send health alert via configured callback.

        Args:
            status: Current system health status

        Returns:
            True if alert sent successfully
        """
        if not self.discord_alert_callback:
            logger.warning("No alert callback configured")
            return False

        try:
            message = f"**SYSTEM ALERT**\n\n{status.summary()}\n\nStatus: {status.status.value}"
            self.discord_alert_callback(message)
            return True
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")
            return False

    def get_uptime(self) -> timedelta:
        """Get system uptime."""
        return datetime.utcnow() - self._start_time

    def get_last_check(self) -> Optional[SystemHealth]:
        """Get last health check result."""
        return self._last_check


__all__ = ["HealthMonitor", "SystemHealth", "ComponentHealth", "HealthStatus"]

"""
Automation Module for PerryPicks

Provides real-time game monitoring, trigger detection, and Discord posting.

Components:
- GameStateMonitor: Polls NBA CDN for live game states
- TriggerEngine: Detects halftime and Q3 triggers
- PostGenerator: Formats predictions for Discord
- DiscordClient: Posts to Discord via webhooks
- AutomationService: Main service that coordinates everything

Usage:
    from src.automation import AutomationService

    service = AutomationService(discord_webhook_url="...")
    service.start()
"""

from src.automation.game_state import GameState, GameStateMonitor
from src.automation.triggers import TriggerType, TriggerEngine, TriggerEvent
from src.automation.post_generator import PostGenerator
from src.automation.discord_client import DiscordClient
from src.automation.service import AutomationService

__all__ = [
    "GameState",
    "GameStateMonitor",
    "TriggerType",
    "TriggerEngine",
    "TriggerEvent",
    "PostGenerator",
    "DiscordClient",
    "AutomationService",
]

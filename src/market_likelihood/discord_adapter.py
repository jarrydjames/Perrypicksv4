from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Dict, Optional

from src.automation.discord_client import DiscordClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiscordAdapterConfig:
    webhook_url: str
    username: str = "PerryPicks"

    @staticmethod
    def from_env() -> "DiscordAdapterConfig":
        url = (
            os.environ.get("DISCORD_LIVE_TRACKING_WEBHOOK")
            or os.environ.get("DISCORD_WEBHOOK_URL")
            or ""
        ).strip()
        return DiscordAdapterConfig(webhook_url=url)


class MarketDiscordPublisher:
    """Thin Discord boundary for the market likelihood engine.

    Prototype responsibilities:
    - create an initial tracking message (wait=true to obtain message_id)
    - edit an existing tracking message (PATCH)

    Non-goals:
    - routing to multiple channels
    - alert fanout
    - rich threading
    """

    def __init__(self, cfg: DiscordAdapterConfig):
        self._cfg = cfg
        self._client = DiscordClient(webhook_url=cfg.webhook_url, username=cfg.username)

    def post_tracker(self, *, content: str = "", embed: Dict) -> Optional[str]:
        res = self._client.post_message(content, embeds=[embed], wait=True)
        if not res.success:
            logger.error("Failed to create tracker message: %s", res.error)
            return None
        return res.message_id

    def edit_tracker(self, *, message_id: str, content: str = "", embed: Dict) -> bool:
        res = self._client.edit_message(message_id=message_id, content=content, embeds=[embed])
        if not res.success:
            logger.error("Failed to edit tracker message: %s", res.error)
            return False
        return True

    def close(self) -> None:
        self._client.close()

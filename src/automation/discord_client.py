"""
Discord Client for PerryPicks

Posts predictions to Discord via webhooks with retry logic
and proper error handling.

Usage:
    from src.automation.discord_client import DiscordClient

    client = DiscordClient(webhook_url="https://discord.com/api/webhooks/...")
    success = client.post_message("Hello from PerryPicks!")
"""

import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


@dataclass
class DiscordPostResult:
    """Result of a Discord post attempt."""

    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None
    retry_count: int = 0


class DiscordClient:
    """
    Discord webhook client with retry logic.

    Posts messages to Discord channels via webhooks with:
    - Exponential backoff on rate limits
    - Proper error handling
    - Message formatting helpers
    """

    # Retry settings
    MAX_RETRIES = 3
    BASE_DELAY = 1.0  # seconds
    MAX_DELAY = 30.0  # seconds

    # Discord API limits
    MAX_CONTENT_LENGTH = 2000

    def __init__(self, webhook_url: str, username: str = "PerryPicks"):
        """
        Initialize Discord client.

        Args:
            webhook_url: Discord webhook URL
            username: Bot username to display

        Raises:
            ValueError: If webhook URL format is invalid
        """
        # Validate webhook URL format (accept both discord.com and discordapp.com)
        if not webhook_url or not (
            webhook_url.startswith("https://discord.com/api/webhooks/") or
            webhook_url.startswith("https://discordapp.com/api/webhooks/")
        ):
            raise ValueError(
                f"Invalid Discord webhook URL format. Expected: https://discord.com/api/webhooks/..."
            )

        self.webhook_url = webhook_url
        self.username = username
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "PerryPicks/1.0",
                "Content-Type": "application/json",
            }
        )

    def __enter__(self) -> "DiscordClient":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Context manager exit - ensure session is closed."""
        self.close()
        return False

    def post_message(
        self,
        content: str,
        embeds: Optional[List[Dict]] = None,
        username: Optional[str] = None,
    ) -> DiscordPostResult:
        """
        Post a message to Discord.

        Args:
            content: Message content (max 2000 chars)
            embeds: Optional list of embed objects
            username: Override username for this message

        Returns:
            DiscordPostResult with success status
        """
        # Truncate content if needed
        if len(content) > self.MAX_CONTENT_LENGTH:
            content = content[: self.MAX_CONTENT_LENGTH - 3] + "..."
            logger.warning("Message truncated to Discord limit")

        payload = {
            "content": content,
            "username": username or self.username,
        }

        if embeds:
            payload["embeds"] = embeds

        return self._post_with_retry(payload)

    def post_embed(
        self,
        title: str,
        description: str,
        color: int = 0x3498DB,  # Blue
        fields: Optional[List[Dict]] = None,
        footer: Optional[str] = None,
    ) -> DiscordPostResult:
        """
        Post a rich embed message.

        Args:
            title: Embed title
            description: Embed description
            color: Embed color (hex)
            fields: List of field dicts with name, value, inline
            footer: Footer text

        Returns:
            DiscordPostResult with success status
        """
        embed = {
            "title": title,
            "description": description,
            "color": color,
        }

        if fields:
            embed["fields"] = fields

        if footer:
            embed["footer"] = {"text": footer}

        return self.post_message("", embeds=[embed])

    def post_halftime_prediction(
        self,
        away_team: str,
        home_team: str,
        h1_away: int,
        h1_home: int,
        pred_total: float,
        pred_margin: float,
        home_win_prob: float,
        total_q10: Optional[float] = None,
        total_q90: Optional[float] = None,
        recommendations: Optional[List[str]] = None,
    ) -> DiscordPostResult:
        """
        Post a formatted halftime prediction.

        Args:
            away_team: Away team tricode
            home_team: Home team tricode
            h1_away: First half away score
            h1_home: First half home score
            pred_total: Predicted final total
            pred_margin: Predicted final margin
            home_win_prob: Home win probability
            total_q10: Total lower bound (80% CI)
            total_q90: Total upper bound (80% CI)
            recommendations: List of betting recommendation strings

        Returns:
            DiscordPostResult with success status
        """
        # Build description
        lines = [
            f"**{away_team} @ {home_team}**",
            f"Half: {h1_away} - {h1_home}",
            "",
            f"**Projected Final**",
            f"Total: {pred_total:.1f}",
            f"Margin: {pred_margin:+.1f}",
            f"Win Prob: {home_win_prob:.1%} {home_team}",
        ]

        if total_q10 is not None and total_q90 is not None:
            lines.append(f"80% CI: {total_q10:.0f} - {total_q90:.0f}")

        description = "\n".join(lines)

        # Build fields
        fields = []

        if recommendations:
            fields.append(
                {
                    "name": "Betting Recommendations",
                    "value": "\n".join(recommendations),
                    "inline": False,
                }
            )

        return self.post_embed(
            title="Halftime Prediction",
            description=description,
            color=0x2ECC71,  # Green
            fields=fields if fields else None,
            footer="PerryPicks REPTAR Model",
        )

    def post_q3_update(
        self,
        away_team: str,
        home_team: str,
        curr_away: int,
        curr_home: int,
        pred_total: float,
        pred_margin: float,
        home_win_prob: float,
    ) -> DiscordPostResult:
        """
        Post a formatted Q3 update.

        Args:
            away_team: Away team tricode
            home_team: Home team tricode
            curr_away: Current away score
            curr_home: Current home score
            pred_total: Predicted final total
            pred_margin: Predicted final margin
            home_win_prob: Home win probability

        Returns:
            DiscordPostResult with success status
        """
        description = "\n".join(
            [
                f"**{away_team} @ {home_team}**",
                f"Current: {curr_away} - {curr_home}",
                "",
                f"**Projected Final**",
                f"Total: {pred_total:.1f}",
                f"Margin: {pred_margin:+.1f}",
                f"Win Prob: {home_win_prob:.1%} {home_team}",
            ]
        )

        return self.post_embed(
            title="Q3 Update (5 Min Left)",
            description=description,
            color=0xF39C12,  # Orange
            footer="PerryPicks REPTAR Model",
        )

    def post_daily_summary(
        self,
        date: str,
        games_monitored: int,
        predictions_posted: int,
        results: Optional[List[Dict]] = None,
    ) -> DiscordPostResult:
        """
        Post a daily summary.

        Args:
            date: Date string
            games_monitored: Number of games monitored
            predictions_posted: Number of predictions posted
            results: Optional list of result dicts

        Returns:
            DiscordPostResult with success status
        """
        fields = [
            {
                "name": "Games Monitored",
                "value": str(games_monitored),
                "inline": True,
            },
            {
                "name": "Predictions Posted",
                "value": str(predictions_posted),
                "inline": True,
            },
        ]

        if results:
            wins = sum(1 for r in results if r.get("correct"))
            total = len(results)
            accuracy = wins / total if total > 0 else 0

            fields.append(
                {
                    "name": "Accuracy",
                    "value": f"{wins}/{total} ({accuracy:.0%})",
                    "inline": True,
                }
            )

        return self.post_embed(
            title=f"Daily Summary - {date}",
            description="PerryPicks automation summary",
            color=0x9B59B6,  # Purple
            fields=fields,
        )

    def _post_with_retry(self, payload: Dict) -> DiscordPostResult:
        """
        Post to Discord with exponential backoff retry.

        Args:
            payload: JSON payload to send

        Returns:
            DiscordPostResult with outcome
        """
        last_error = None

        for attempt in range(self.MAX_RETRIES):
            try:
                response = self._session.post(self.webhook_url, json=payload, timeout=30)

                if response.status_code == 204:
                    # Success (no content)
                    logger.info("Discord post successful")
                    return DiscordPostResult(success=True, retry_count=attempt)

                if response.status_code == 200:
                    # Success with response - CRITICAL FIX: Handle JSON parse errors
                    try:
                        data = response.json()
                        message_id = data.get("id")
                        logger.info(f"Discord post successful: {message_id}")
                        return DiscordPostResult(
                            success=True, message_id=message_id, retry_count=attempt
                        )
                    except ValueError as e:
                        logger.error(f"Invalid JSON response from Discord: {e}")
                        time.sleep(self._get_delay(attempt))
                        continue

                if response.status_code == 429:
                    # Rate limited - wait and retry
                    # CRITICAL FIX: Handle malformed Retry-After header safely
                    retry_after = response.headers.get("Retry-After")
                    try:
                        delay = float(retry_after) if retry_after else self._get_delay(attempt)
                    except (ValueError, TypeError):
                        delay = self._get_delay(attempt)
                    logger.warning(f"Discord rate limited, waiting {delay}s")
                    time.sleep(delay)
                    continue

                # Other error
                last_error = f"Discord API error: {response.status_code}"
                logger.error(last_error)

                if response.status_code >= 500:
                    # Server error - retry
                    time.sleep(self._get_delay(attempt))
                    continue

                # Client error - don't retry (except 400/408 which may be transient)
                if response.status_code in (400, 408):
                    time.sleep(self._get_delay(attempt))
                    continue

                return DiscordPostResult(success=False, error=last_error, retry_count=attempt)

            except requests.Timeout:
                last_error = "Request timeout"
                logger.warning(f"Discord request timeout, attempt {attempt + 1}")
                time.sleep(self._get_delay(attempt))

            except requests.RequestException as e:
                last_error = f"Request error: {e}"
                logger.error(f"Discord request error: {e}")
                time.sleep(self._get_delay(attempt))

        return DiscordPostResult(success=False, error=last_error, retry_count=self.MAX_RETRIES)

    def _get_delay(self, attempt: int) -> float:
        """Calculate delay for exponential backoff."""
        delay = self.BASE_DELAY * (2**attempt)
        return min(delay, self.MAX_DELAY)

    def close(self) -> None:
        """Close the HTTP session."""
        self._session.close()


__all__ = ["DiscordClient", "DiscordPostResult"]

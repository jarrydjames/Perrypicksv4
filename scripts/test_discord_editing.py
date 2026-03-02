"""Manual test: Discord webhook post(wait=true) + edit.

This script is intentionally manual and should be run by a human when desired.

It will:
- post a single embed to DISCORD_LIVE_TRACKING_WEBHOOK (or DISCORD_WEBHOOK_URL fallback)
- edit the same message a few times

Run:
  .venv/bin/python scripts/test_discord_editing.py

Notes:
- Do NOT commit real webhook URLs.
- Rotate webhook if it was ever pasted into logs/chat.
"""

from __future__ import annotations

# Ensure we import from THIS repo (v5), not a sibling checkout (v4).
import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import os
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from src.automation.discord_client import DiscordClient
import inspect


def _must_env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise SystemExit(f"Missing required env var: {name}")
    return v


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    webhook = (os.environ.get("DISCORD_LIVE_TRACKING_WEBHOOK") or os.environ.get("DISCORD_WEBHOOK_URL") or "").strip()
    if not webhook:
        raise SystemExit("Missing DISCORD_LIVE_TRACKING_WEBHOOK (or DISCORD_WEBHOOK_URL fallback)")

    client = DiscordClient(webhook_url=webhook, username="PerryPicks")
    import src.automation.discord_client as dc
    print("discord_client module:", dc.__file__)
    print("DiscordClient.post_message sig:", inspect.signature(DiscordClient.post_message))
    print("has edit_message:", hasattr(DiscordClient, "edit_message"))

    embed = {
        "title": "🧪 Discord Edit Test",
        "description": "Posting initial message...",
        "color": 0x3498DB,
        "footer": {"text": "market likelihood prototype"},
    }

    res = client.post_message("", embeds=[embed], wait=True)
    if not res.success or not res.message_id:
        raise SystemExit(f"Post failed: {res.error}")

    mid = res.message_id

    for i in range(1, 4):
        embed2 = {
            "title": "🧪 Discord Edit Test",
            "description": f"Edit #{i} at {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}",
            "color": 0x2ECC71,
            "footer": {"text": f"edit {i}"},
        }
        r2 = client.edit_message(message_id=mid, content="", embeds=[embed2])
        if not r2.success:
            raise SystemExit(f"Edit failed: {r2.error}")
        time.sleep(2)

    print("OK: posted and edited message_id:", mid)


if __name__ == "__main__":
    main()

"""Prototype runner stub for the market likelihood engine.

Not wired into live automation yet.

Intended future behavior:
- load tracked tickets (DB)
- fetch latest odds snapshots
- compute likelihood estimates
- edit a single Discord message per ticket

This file exists to keep `start.py` from getting even more cursed.
"""

from __future__ import annotations

import logging


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logging.getLogger(__name__).info("market likelihood runner stub (no-op)")


if __name__ == "__main__":
    main()

"""DB maintenance utilities.

Goal: keep SQLite from growing forever in a multi-process daemon setup.

This module intentionally uses `sqlite3` directly:
- avoids SQLAlchemy session/metadata overhead
- minimal imports
- safe to run from watchdog

Zen rule: explicit > implicit.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Tuple


@dataclass(frozen=True)
class MaintenanceConfig:
    points_retention_days: int = 7
    finalized_messages_retention_days: int = 30
    stale_active_fail_after_days: int = 2


def _db_path() -> Path:
    # Single source of truth: dashboard/backend/perrypicks_dashboard.db
    return Path(__file__).resolve().parents[2] / "dashboard" / "backend" / "perrypicks_dashboard.db"


def run_market_tracking_cleanup(*, cfg: MaintenanceConfig | None = None) -> Tuple[int, int, int, int]:
    """Cleanup market tracking tables.

    Returns:
        (points_deleted, messages_deleted, messages_finalized, messages_failed)
    """

    cfg = cfg or MaintenanceConfig(
        points_retention_days=int(os.environ.get("DB_MAINT_POINTS_RETENTION_DAYS", "7")),
        finalized_messages_retention_days=int(
            os.environ.get("DB_MAINT_FINALIZED_MESSAGES_RETENTION_DAYS", "30")
        ),
        stale_active_fail_after_days=int(os.environ.get("DB_MAINT_STALE_ACTIVE_FAIL_AFTER_DAYS", "2")),
    )

    now_utc = datetime.now(timezone.utc)
    points_cutoff = now_utc - timedelta(days=cfg.points_retention_days)
    messages_cutoff = now_utc - timedelta(days=cfg.finalized_messages_retention_days)

    db_path = _db_path()
    if not db_path.exists():
        return (0, 0, 0, 0)

    points_deleted = 0
    messages_deleted = 0

    # Store naive timestamps because DB uses naive UTC
    points_cutoff_naive = points_cutoff.replace(tzinfo=None)
    messages_cutoff_naive = messages_cutoff.replace(tzinfo=None)

    con = sqlite3.connect(str(db_path), timeout=30)
    try:
        con.execute("PRAGMA busy_timeout=5000")
        con.execute("PRAGMA foreign_keys=ON")

        # Delete old points
        cur = con.execute(
            "DELETE FROM market_tracking_points WHERE timestamp_utc < ?",
            (points_cutoff_naive.isoformat(sep=" "),),
        )
        points_deleted = cur.rowcount or 0

        # Delete old finalized messages
        cur = con.execute(
            "DELETE FROM market_tracking_messages WHERE status = 'finalized' AND updated_at < ?",
            (messages_cutoff_naive.isoformat(sep=" "),),
        )
        messages_deleted = cur.rowcount or 0

        # Reconcile stale active trackers so they don't churn forever
        # 1) If the underlying game is Final OR rec.result is not pending -> mark finalized
        cur = con.execute(
            """
            UPDATE market_tracking_messages
            SET status = 'finalized', updated_at = CURRENT_TIMESTAMP
            WHERE id IN (
                SELECT mtm.id
                FROM market_tracking_messages mtm
                JOIN betting_recommendations br ON br.id = mtm.recommendation_id
                JOIN predictions p ON p.id = br.prediction_id
                JOIN games g ON g.id = p.game_id
                WHERE mtm.status = 'active'
                  AND (
                      lower(coalesce(g.game_status, '')) = 'final'
                      OR lower(coalesce(br.result, 'pending')) != 'pending'
                  )
            )
            """
        )
        messages_finalized = cur.rowcount or 0

        # 2) If still active but game is ancient -> mark failed
        fail_cutoff = (now_utc - timedelta(days=cfg.stale_active_fail_after_days)).replace(tzinfo=None)
        cur = con.execute(
            """
            UPDATE market_tracking_messages
            SET status = 'failed', updated_at = CURRENT_TIMESTAMP
            WHERE id IN (
                SELECT mtm.id
                FROM market_tracking_messages mtm
                JOIN betting_recommendations br ON br.id = mtm.recommendation_id
                JOIN predictions p ON p.id = br.prediction_id
                JOIN games g ON g.id = p.game_id
                WHERE mtm.status = 'active'
                  AND g.game_date < ?
            )
            """,
            (fail_cutoff.isoformat(sep=' '),),
        )
        messages_failed = cur.rowcount or 0

        con.commit()
        return (points_deleted, messages_deleted, messages_finalized, messages_failed)
    finally:
        con.close()

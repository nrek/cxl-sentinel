"""Lightweight SQLite schema fixes for existing databases.

`Base.metadata.create_all()` does not add columns to tables that already exist.
This module applies ALTER TABLE for columns added after the first deploy.
"""

import logging
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

logger = logging.getLogger("sentinel.api.sqlite_migrations")


def apply_sqlite_migrations(engine: "Engine") -> None:
    url = str(engine.url)
    if not url.startswith("sqlite"):
        return

    with engine.begin() as conn:
        _ensure_deploy_events_columns(conn)
    logger.debug("SQLite migrations applied (if any)")


def _ensure_deploy_events_columns(conn) -> None:
    try:
        result = conn.execute(text("PRAGMA table_info(deploy_events)"))
    except Exception as e:
        logger.warning("PRAGMA deploy_events skipped (table may not exist yet): %s", e)
        return

    columns = {row[1] for row in result}

    if "commit_count" not in columns:
        conn.execute(
            text("ALTER TABLE deploy_events ADD COLUMN commit_count INTEGER DEFAULT 1"),
        )
        logger.info("Added column deploy_events.commit_count")

    if "contributors" not in columns:
        conn.execute(text("ALTER TABLE deploy_events ADD COLUMN contributors TEXT"))
        logger.info("Added column deploy_events.contributors")

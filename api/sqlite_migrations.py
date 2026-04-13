"""SQLite schema migrations applied at startup.

With the v2 schema (repo_alias, no client), existing databases from v1 are not
compatible. Run `python api/manage.py init-db` to drop and recreate tables.
"""

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger("sentinel.api.sqlite_migrations")


def apply_sqlite_migrations(engine: Engine) -> None:
    """Run any needed SQLite schema patches. No-op for clean v2 databases."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1 FROM deploy_events LIMIT 0"))
            conn.execute(text("SELECT 1 FROM digest_state LIMIT 0"))
            logger.debug("SQLite schema looks current")
    except Exception:
        logger.warning(
            "Schema check failed — run `python api/manage.py init-db` to create or recreate tables."
        )

"""Database engine and session management."""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

_engine = None
_SessionLocal = None


def init_engine(database_url: str) -> None:
    """Initialize the SQLAlchemy engine and session factory."""
    global _engine, _SessionLocal

    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    _engine = create_engine(
        database_url,
        connect_args=connect_args,
        pool_pre_ping=True,
    )

    if database_url.startswith("sqlite"):
        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    _SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)


def get_engine():
    if _engine is None:
        raise RuntimeError("Database engine not initialized. Call init_engine() first.")
    return _engine


def get_session() -> Session:
    """Yield a database session for dependency injection."""
    if _SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_engine() first.")
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()

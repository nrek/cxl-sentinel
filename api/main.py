"""CXL Sentinel API -- FastAPI application entry point."""

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from api.config import load_api_config
from api.database import init_engine, get_engine
from api.models import Base
from api.routers import events, heartbeat, servers, health
from api.sqlite_migrations import apply_sqlite_migrations

logger = logging.getLogger("sentinel.api")

_VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"


def _get_version() -> str:
    try:
        return _VERSION_FILE.read_text().strip()
    except OSError:
        return "unknown"


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    config_path = os.environ.get("SENTINEL_CONFIG", "api/config.yaml")
    try:
        config = load_api_config(config_path)
    except (FileNotFoundError, ValueError) as e:
        # stderr so systemd/journal always shows the reason (logging may not be configured yet)
        print(f"sentinel-api: failed to load config {config_path!r}: {e}", file=sys.stderr, flush=True)
        logger.error("Failed to load config: %s", e)
        sys.exit(1)

    _setup_logging(config.log_level)
    init_engine(config.database_url)

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    apply_sqlite_migrations(engine)

    app.state.config = config
    logger.info("CXL Sentinel API v%s started", _get_version())
    yield
    logger.info("CXL Sentinel API shutting down")


app = FastAPI(
    title="CXL Sentinel",
    description="Deployment tracking API for manually deployed web applications",
    version=_get_version(),
    lifespan=lifespan,
)

app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(events.router, prefix="/api/v1", tags=["events"])
app.include_router(heartbeat.router, prefix="/api/v1", tags=["heartbeat"])
app.include_router(servers.router, prefix="/api/v1", tags=["servers"])


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )

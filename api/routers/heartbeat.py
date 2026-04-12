"""Heartbeat endpoint for agent liveness tracking."""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api.auth import require_role
from api.database import get_session
from api.models import ServerHeartbeat
from api.schemas import HeartbeatCreate, HeartbeatResponse

logger = logging.getLogger("sentinel.api.heartbeat")

router = APIRouter()


@router.post(
    "/heartbeat",
    response_model=HeartbeatResponse,
    dependencies=[Depends(require_role("agent", "admin"))],
)
async def receive_heartbeat(
    payload: HeartbeatCreate,
    session: Session = Depends(get_session),
):
    now = datetime.now(timezone.utc)
    projects_json = json.dumps(payload.projects_watched)

    existing = session.query(ServerHeartbeat).filter(
        ServerHeartbeat.server_id == payload.server_id,
    ).first()

    if existing:
        existing.environment = payload.environment
        existing.projects_watched = projects_json
        existing.agent_version = payload.agent_version
        existing.last_seen = now
    else:
        hb = ServerHeartbeat(
            server_id=payload.server_id,
            environment=payload.environment,
            projects_watched=projects_json,
            agent_version=payload.agent_version,
            last_seen=now,
        )
        session.add(hb)

    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        logger.exception("Heartbeat DB commit failed for server_id=%s", payload.server_id)
        raise

    logger.debug("Heartbeat from %s (v%s)", payload.server_id, payload.agent_version)
    return HeartbeatResponse(status="ok", server_time=now)

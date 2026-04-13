"""Server listing endpoint."""

import json
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth import require_role
from api.database import get_session
from api.models import ServerHeartbeat
from api.schemas import ServerDetail

logger = logging.getLogger("sentinel.api.servers")

router = APIRouter()

ALIVE_THRESHOLD = timedelta(minutes=15)


@router.get(
    "/servers",
    response_model=list[ServerDetail],
    dependencies=[Depends(require_role("admin", "readonly"))],
)
async def list_servers(session: Session = Depends(get_session)):
    now = datetime.now(timezone.utc)
    heartbeats = session.query(ServerHeartbeat).order_by(ServerHeartbeat.last_seen.desc()).all()

    results = []
    for hb in heartbeats:
        try:
            repos = json.loads(hb.repos_watched) if hb.repos_watched else []
        except (json.JSONDecodeError, TypeError):
            repos = []

        last_seen = hb.last_seen
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)

        is_alive = (now - last_seen) < ALIVE_THRESHOLD

        results.append(ServerDetail(
            server_id=hb.server_id,
            environment=hb.environment,
            repos_watched=repos,
            agent_version=hb.agent_version,
            last_seen=last_seen,
            is_alive=is_alive,
        ))

    return results

"""Deploy event endpoints."""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.auth import require_role
from api.database import get_session
from api.models import DeployEvent
from api.notifications.dispatcher import dispatch_immediate_notification
from api.notifications.renderer import _commit_requests_immediate_notify
from api.schemas import DeployEventCreate, DeployEventDetail, DeployEventResponse

logger = logging.getLogger("sentinel.api.events")

router = APIRouter()


@router.post(
    "/events",
    response_model=DeployEventResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role("agent", "admin"))],
)
async def create_event(
    payload: DeployEventCreate,
    request: Request,
    session: Session = Depends(get_session),
):
    is_notify = _commit_requests_immediate_notify(payload.commit_message or "")

    event = DeployEvent(
        server_id=payload.server_id,
        environment=payload.environment,
        repo_alias=payload.repo_alias,
        branch=payload.branch,
        commit_hash=payload.commit_hash,
        commit_message=payload.commit_message,
        commit_author=payload.commit_author,
        commit_timestamp=payload.commit_timestamp,
        previous_commit_hash=payload.previous_commit_hash,
        files_changed=payload.files_changed,
        commit_count=payload.commit_count,
        contributors=json.dumps(payload.contributors) if payload.contributors else None,
        detected_at=payload.detected_at,
        notified_immediately=is_notify,
    )

    try:
        session.add(event)
        session.commit()
        session.refresh(event)
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Deploy event already recorded (duplicate server_id + repo_alias + commit_hash)",
        )

    logger.info(
        "Recorded deploy: %s/%s@%s on %s",
        payload.repo_alias, payload.commit_hash[:12], payload.environment, payload.server_id,
    )

    if is_notify:
        _fire_immediate_notification(request, payload)

    return DeployEventResponse(id=event.id)


def _fire_immediate_notification(request: Request, payload: DeployEventCreate) -> None:
    """Send an immediate [NOTIFY] email. Failures are logged, never block the response."""
    try:
        config = request.app.state.config
        detected_str = payload.detected_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        dispatch_immediate_notification(
            config=config.notifications,
            repo_alias=payload.repo_alias,
            server_id=payload.server_id,
            environment=payload.environment,
            commit_hash=payload.commit_hash,
            commit_message=payload.commit_message,
            commit_author=payload.commit_author,
            files_changed=payload.files_changed,
            commit_count=payload.commit_count,
            contributors=payload.contributors,
            branch=payload.branch,
            detected_at=detected_str,
            previous_commit_hash=payload.previous_commit_hash,
        )
    except Exception:
        logger.exception("[NOTIFY] immediate notification dispatch failed (non-blocking)")


@router.get(
    "/events",
    response_model=list[DeployEventDetail],
    dependencies=[Depends(require_role("admin", "readonly"))],
)
async def list_events(
    server_id: Optional[str] = Query(None),
    repo_alias: Optional[str] = Query(None),
    environment: Optional[str] = Query(None),
    since: Optional[datetime] = Query(None),
    until: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    session: Session = Depends(get_session),
):
    query = session.query(DeployEvent)

    if server_id:
        query = query.filter(DeployEvent.server_id == server_id)
    if repo_alias:
        query = query.filter(DeployEvent.repo_alias == repo_alias)
    if environment:
        query = query.filter(DeployEvent.environment == environment)
    if since:
        query = query.filter(DeployEvent.detected_at >= since)
    if until:
        query = query.filter(DeployEvent.detected_at <= until)

    events = query.order_by(DeployEvent.detected_at.desc()).limit(limit).all()
    return events

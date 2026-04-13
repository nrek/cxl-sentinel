"""Background digest scheduler.

Runs as an asyncio task inside the FastAPI lifespan. Every 60 seconds it checks
each notification rule to see if the current time has crossed the next digest
window boundary (anchored at midnight UTC). When a window is due, it queries
un-digested deploy events and sends a summary email.
"""

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone, timedelta
from math import floor

from sqlalchemy.orm import Session

from api.config import NotificationsConfig, ServerNotificationRule
from api.database import get_session
from api.models import DeployEvent, DigestState
from api.notifications.dispatcher import dispatch_digest

logger = logging.getLogger("sentinel.digest_scheduler")

_TICK_SECONDS = 60


def _rule_key(rule: ServerNotificationRule, environment: str) -> str:
    """Deterministic hash key for a rule + environment combination."""
    raw = f"{rule.server_id}|{environment}|{','.join(sorted(rule.recipients))}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _current_window_start(now: datetime, interval_seconds: int) -> datetime:
    """Return the start of the current digest window, anchored at midnight UTC."""
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = (now - midnight).total_seconds()
    window_index = floor(elapsed / interval_seconds)
    return midnight + timedelta(seconds=window_index * interval_seconds)


def _is_window_due(
    now: datetime,
    interval_seconds: int,
    last_sent_at: datetime | None,
) -> bool:
    """Check if a new digest window has been entered since last_sent_at."""
    window_start = _current_window_start(now, interval_seconds)
    if last_sent_at is None:
        return True
    return last_sent_at < window_start


def _get_or_create_digest_state(session: Session, key: str) -> DigestState:
    state = session.query(DigestState).filter(DigestState.rule_key == key).first()
    if state is None:
        state = DigestState(rule_key=key, last_sent_at=datetime.now(timezone.utc))
        session.add(state)
        session.commit()
    return state


def _query_events_since(
    session: Session,
    server_id: str,
    environment: str,
    since: datetime,
) -> list[DeployEvent]:
    """Fetch deploy events for this server_id + environment since the given timestamp."""
    q = session.query(DeployEvent).filter(
        DeployEvent.environment == environment,
        DeployEvent.detected_at > since,
    )
    if server_id != "*":
        q = q.filter(DeployEvent.server_id == server_id)
    return q.order_by(DeployEvent.detected_at.asc()).all()


def _event_to_dict(ev: DeployEvent) -> dict:
    contributors = []
    if ev.contributors:
        try:
            contributors = json.loads(ev.contributors)
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "repo_alias": ev.repo_alias,
        "commit_hash": ev.commit_hash,
        "commit_message": ev.commit_message or "",
        "commit_author": ev.commit_author or "",
        "files_changed": ev.files_changed or 0,
        "commit_count": ev.commit_count or 1,
        "contributors": contributors,
        "branch": ev.branch or "main",
        "detected_at": ev.detected_at.strftime("%Y-%m-%d %H:%M UTC") if ev.detected_at else "",
        "notified_immediately": bool(ev.notified_immediately),
    }


def process_digest_tick(notifications: NotificationsConfig) -> int:
    """Run one digest tick. Returns the number of digest emails sent."""
    now = datetime.now(timezone.utc)
    sent_count = 0

    session_gen = get_session()
    session = next(session_gen)
    try:
        for rule in notifications.rules:
            for env in rule.environments:
                key = _rule_key(rule, env)
                state = _get_or_create_digest_state(session, key)

                if not _is_window_due(now, rule.send_schedule_seconds, state.last_sent_at):
                    continue

                events = _query_events_since(session, rule.server_id, env, state.last_sent_at)
                if not events:
                    state.last_sent_at = now
                    session.commit()
                    continue

                event_dicts = [_event_to_dict(ev) for ev in events]

                ok = dispatch_digest(
                    config=notifications,
                    rule=rule,
                    environment=env,
                    events=event_dicts,
                )

                if ok:
                    state.last_sent_at = now
                    session.commit()
                    sent_count += 1
                    logger.info(
                        "Digest sent for %s/%s: %d events",
                        rule.server_id, env, len(events),
                    )
                else:
                    logger.warning("Digest send failed for %s/%s", rule.server_id, env)

    except Exception:
        logger.exception("Error during digest tick")
    finally:
        session.close()
        try:
            session_gen.close()
        except Exception:
            pass

    return sent_count


async def run_digest_scheduler(notifications: NotificationsConfig) -> None:
    """Long-running coroutine that ticks every 60 seconds to check digest windows."""
    logger.info("Digest scheduler started (tick every %ds)", _TICK_SECONDS)

    while True:
        try:
            sent = await asyncio.to_thread(process_digest_tick, notifications)
            if sent:
                logger.info("Digest tick: sent %d email(s)", sent)
        except asyncio.CancelledError:
            logger.info("Digest scheduler cancelled")
            break
        except Exception:
            logger.exception("Unhandled error in digest scheduler tick")

        await asyncio.sleep(_TICK_SECONDS)

"""Notification dispatcher -- routes deploy events to configured email providers.

Matches deploy events against notification rules to determine recipients,
renders the HTML email, and sends via the active provider (SMTP or SendGrid).
"""

import logging
from fnmatch import fnmatch
from typing import Optional

from api.config import NotificationsConfig, ProjectNotificationRule
from api.notifications.renderer import render_deploy_email
from api.notifications import smtp_provider, sendgrid_provider

logger = logging.getLogger("sentinel.notifications.dispatcher")


def dispatch_deploy_notification(
    config: NotificationsConfig,
    project: str,
    client: str,
    server_id: str,
    environment: str,
    commit_hash: str,
    commit_message: Optional[str],
    commit_author: Optional[str],
    files_changed: int,
    commit_count: int,
    contributors: list[str],
    branch: str,
    detected_at: str,
    previous_commit_hash: Optional[str],
) -> None:
    """Evaluate notification rules and send emails for a deploy event.

    This is fire-and-forget: failures are logged but do not raise.
    """
    if not config.smtp.enabled and not config.sendgrid.enabled:
        return

    recipients = _resolve_recipients(config.rules, project, client, environment)
    if not recipients:
        logger.debug("No notification recipients matched for %s/%s (%s)", client, project, environment)
        return

    try:
        subject, html_body = render_deploy_email(
            project=project,
            client=client,
            server_id=server_id,
            environment=environment,
            commit_hash=commit_hash,
            commit_message=commit_message or "",
            commit_author=commit_author or "",
            files_changed=files_changed,
            commit_count=commit_count,
            contributors=contributors or [],
            branch=branch,
            detected_at=detected_at,
            previous_commit_hash=previous_commit_hash,
            branding=config.branding,
        )
    except Exception:
        logger.exception("Failed to render deploy notification email")
        return

    sent = False

    if config.sendgrid.enabled:
        sent = sendgrid_provider.send_email(config.sendgrid, recipients, subject, html_body)
    elif config.smtp.enabled:
        sent = smtp_provider.send_email(config.smtp, recipients, subject, html_body)

    if sent:
        logger.info(
            "Deploy notification sent for %s/%s to %d recipient(s)",
            client, project, len(recipients),
        )
    else:
        logger.warning(
            "Deploy notification failed for %s/%s — recipients: %s",
            client, project, ", ".join(recipients),
        )


def _resolve_recipients(
    rules: list[ProjectNotificationRule],
    project: str,
    client: str,
    environment: str,
) -> list[str]:
    """Collect unique recipients from all matching rules."""
    recipients = set()

    for rule in rules:
        if environment not in rule.environments:
            continue
        if not _matches(rule.project, project):
            continue
        if not _matches(rule.client, client):
            continue
        recipients.update(rule.recipients)

    return sorted(recipients)


def _matches(pattern: str, value: str) -> bool:
    """Check if a value matches a pattern. '*' matches everything."""
    if pattern == "*":
        return True
    return fnmatch(value.lower(), pattern.lower())

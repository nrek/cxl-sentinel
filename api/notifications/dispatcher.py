"""Notification dispatcher -- routes deploy events to configured email providers.

Matches deploy events against notification rules to determine recipients,
renders the HTML email, and sends via the active provider (SMTP or SendGrid).
"""

import logging
from fnmatch import fnmatch
from typing import Optional

from api.config import NotificationsConfig, ServerNotificationRule
from api.notifications.renderer import render_deploy_email, render_digest_email
from api.notifications import smtp_provider, sendgrid_provider

logger = logging.getLogger("sentinel.notifications.dispatcher")


def dispatch_immediate_notification(
    config: NotificationsConfig,
    repo_alias: str,
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
    """Send an immediate [NOTIFY] email for a single deploy event.

    Fire-and-forget: failures are logged but do not raise.
    """
    if not config.smtp.enabled and not config.sendgrid.enabled:
        return

    recipients = _resolve_recipients(config.rules, server_id, environment)
    if not recipients:
        logger.debug("No notification recipients matched for %s (%s)", server_id, environment)
        return

    try:
        subject, html_body = render_deploy_email(
            repo_alias=repo_alias,
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

    _send(config, recipients, subject, html_body,
           label=f"[NOTIFY] {repo_alias}@{server_id}/{environment}")


def dispatch_digest(
    config: NotificationsConfig,
    rule: ServerNotificationRule,
    environment: str,
    events: list[dict],
) -> bool:
    """Render and send a digest email for a batch of deploy events.

    Returns True if the email was sent successfully.
    """
    if not config.smtp.enabled and not config.sendgrid.enabled:
        return False

    if not rule.recipients:
        return False

    server_alias = rule.server_alias or rule.server_id

    try:
        subject, html_body = render_digest_email(
            server_alias=server_alias,
            server_id=rule.server_id,
            environment=environment,
            events=events,
            branding=config.branding,
        )
    except Exception:
        logger.exception("Failed to render digest email for %s/%s", rule.server_id, environment)
        return False

    return _send(config, list(rule.recipients), subject, html_body,
                  label=f"digest {rule.server_id}/{environment}")


def _send(
    config: NotificationsConfig,
    recipients: list[str],
    subject: str,
    html_body: str,
    label: str,
) -> bool:
    use_bcc = config.use_bcc
    to_address = config.to_address or ""

    sent = False
    if config.sendgrid.enabled:
        sent = sendgrid_provider.send_email(
            config.sendgrid, recipients, subject, html_body,
            use_bcc=use_bcc, to_address=to_address,
        )
    elif config.smtp.enabled:
        sent = smtp_provider.send_email(
            config.smtp, recipients, subject, html_body,
            use_bcc=use_bcc, to_address=to_address,
        )

    if sent:
        logger.info("Notification sent (%s) to %d recipient(s)", label, len(recipients))
    else:
        logger.warning("Notification failed (%s) — recipients: %s", label, ", ".join(recipients))
    return sent


def _resolve_recipients(
    rules: list[ServerNotificationRule],
    server_id: str,
    environment: str,
) -> list[str]:
    """Collect unique recipients from all matching rules."""
    recipients = set()

    for rule in rules:
        if environment not in rule.environments:
            continue
        if not _matches(rule.server_id, server_id):
            continue
        recipients.update(rule.recipients)

    return sorted(recipients)


def _matches(pattern: str, value: str) -> bool:
    """Check if a value matches a pattern. '*' matches everything."""
    if pattern == "*":
        return True
    return fnmatch(value.lower(), pattern.lower())

"""SendGrid email provider for deploy notifications.

Uses the SendGrid v3 Mail Send API directly via requests,
avoiding the heavy sendgrid-python SDK.
When use_bcc is True, recipients are placed in BCC and the TO line
shows to_address (or from_address as fallback).
"""

import logging

import requests

from api.config import SendGridConfig

logger = logging.getLogger("sentinel.notifications.sendgrid")

_SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"


def send_email(
    config: SendGridConfig,
    recipients: list[str],
    subject: str,
    html_body: str,
    *,
    use_bcc: bool = True,
    to_address: str = "",
) -> bool:
    """Send an HTML email via SendGrid."""
    if not recipients:
        logger.debug("No recipients, skipping SendGrid send")
        return True

    visible_to = to_address or config.from_address

    if use_bcc:
        personalization = {
            "to": [{"email": visible_to}],
            "bcc": [{"email": addr} for addr in recipients],
            "subject": subject,
        }
    else:
        personalization = {
            "to": [{"email": addr} for addr in recipients],
            "subject": subject,
        }

    payload = {
        "personalizations": [personalization],
        "from": {
            "email": config.from_address,
            "name": config.from_name,
        },
        "content": [
            {
                "type": "text/html",
                "value": html_body,
            }
        ],
    }

    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(
            _SENDGRID_API_URL, json=payload, headers=headers, timeout=30,
        )

        if resp.status_code in (200, 201, 202):
            logger.info(
                "Email sent via SendGrid to %d recipient(s): %s",
                len(recipients), subject,
            )
            return True

        logger.error(
            "SendGrid API returned %d: %s", resp.status_code, resp.text[:300],
        )
        return False

    except requests.RequestException as e:
        logger.error("SendGrid request failed: %s", e)
        return False

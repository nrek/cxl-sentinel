"""SMTP email provider for deploy notifications.

Supports standard SMTP (Gmail, Outlook, self-hosted) with TLS.
When use_bcc is True, recipients are placed in BCC and the TO line
shows to_address (or from_address as fallback).
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from api.config import SmtpConfig

logger = logging.getLogger("sentinel.notifications.smtp")


def send_email(
    config: SmtpConfig,
    recipients: list[str],
    subject: str,
    html_body: str,
    *,
    use_bcc: bool = True,
    to_address: str = "",
) -> bool:
    """Send an HTML email via SMTP."""
    if not recipients:
        logger.debug("No recipients, skipping SMTP send")
        return True

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{config.from_name} <{config.from_address}>"

    if use_bcc:
        visible_to = to_address or config.from_address
        msg["To"] = visible_to
        envelope_recipients = list({visible_to} | set(recipients))
    else:
        msg["To"] = ", ".join(recipients)
        envelope_recipients = list(recipients)

    plain_text = _html_to_plain_fallback(subject)
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        if config.use_tls:
            server = smtplib.SMTP(config.host, config.port, timeout=30)
            server.ehlo()
            server.starttls()
            server.ehlo()
        else:
            server = smtplib.SMTP(config.host, config.port, timeout=30)

        if config.username and config.password:
            server.login(config.username, config.password)

        server.sendmail(config.from_address, envelope_recipients, msg.as_string())
        server.quit()

        logger.info("Email sent via SMTP to %d recipient(s): %s", len(recipients), subject)
        return True

    except smtplib.SMTPException as e:
        logger.error("SMTP send failed: %s", e)
        return False
    except OSError as e:
        logger.error("SMTP connection error: %s", e)
        return False


def _html_to_plain_fallback(subject: str) -> str:
    """Minimal plain-text fallback for email clients that don't render HTML."""
    return f"{subject}\n\nView this email in an HTML-capable client for full details."

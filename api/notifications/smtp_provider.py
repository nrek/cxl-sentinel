"""SMTP email provider for deploy notifications.

Supports standard SMTP (Gmail, Outlook, self-hosted) with TLS.
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
) -> bool:
    """Send an HTML email via SMTP.

    Args:
        config: SMTP connection settings.
        recipients: List of email addresses.
        subject: Email subject line.
        html_body: Rendered HTML content.

    Returns:
        True on success, False on failure.
    """
    if not recipients:
        logger.debug("No recipients, skipping SMTP send")
        return True

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{config.from_name} <{config.from_address}>"
    msg["To"] = ", ".join(recipients)

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

        server.sendmail(config.from_address, recipients, msg.as_string())
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

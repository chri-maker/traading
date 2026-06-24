"""Email notifications via SMTP (defaults to Gmail).

Gmail requires an *App Password* (not your normal password) with 2FA enabled:
https://support.google.com/accounts/answer/185833
Set SMTP_USER to your Gmail address and SMTP_PASS to the 16-char app password.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from .config import CongressConfig

log = logging.getLogger(__name__)


def send_email(config: CongressConfig, subject: str, body: str) -> bool:
    """Send a plain-text email. Returns True on success, False otherwise.

    If email isn't configured, logs the body and returns False (so the job can
    still run as a no-email dry run).
    """
    if not config.email_configured:
        log.warning("Email not configured; summary would have been:\n%s", body)
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.email_from or config.smtp_user
    message["To"] = config.email_to
    message.set_content(body)

    try:
        with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=30) as server:
            server.starttls()
            server.login(config.smtp_user, config.smtp_pass)
            server.send_message(message)
        log.info("Sent summary email to %s", config.email_to)
        return True
    except Exception:
        log.exception("Failed to send email")
        return False

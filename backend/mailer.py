"""Tiny SMTP helper. Always called from a background task so a slow mail server never blocks a request."""

import logging
import smtplib
from email.message import EmailMessage
from typing import Optional

import config

log = logging.getLogger("gitsetlive.mail")


def enabled() -> bool:
    return bool(config.SMTP_EMAIL and config.SMTP_PASSWORD)


def send_email(to_email: str, subject: str, text: str, html: Optional[str] = None) -> bool:
    if not enabled() or not to_email or "@" not in to_email:
        return False
    msg = EmailMessage()
    msg["From"] = config.SMTP_EMAIL
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(config.SMTP_EMAIL, config.SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:  # noqa: BLE001 — mail failure must never break the caller
        log.warning("email to %s failed: %s", to_email, type(e).__name__)
        return False

import asyncio
from email.message import EmailMessage
from email.utils import formataddr
import logging
import smtplib
import ssl

from .config import settings

logger = logging.getLogger("certificate_manager.email")


def email_smtp_configured() -> bool:
    return bool(settings.email_smtp_host and settings.email_smtp_username and settings.email_smtp_password)


def _send_sync(recipient: str, subject: str, text_body: str, html_body: str | None = None) -> None:
    sender = settings.email_smtp_from.strip() or settings.email_smtp_username.strip()
    message = EmailMessage()
    message["From"] = formataddr(("证事提醒", sender))
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    context = ssl.create_default_context()
    if settings.email_smtp_use_ssl:
        with smtplib.SMTP_SSL(settings.email_smtp_host, settings.email_smtp_port, timeout=15, context=context) as server:
            server.login(settings.email_smtp_username, settings.email_smtp_password)
            server.send_message(message)
    else:
        with smtplib.SMTP(settings.email_smtp_host, settings.email_smtp_port, timeout=15) as server:
            server.ehlo()
            if settings.email_smtp_starttls:
                server.starttls(context=context)
                server.ehlo()
            server.login(settings.email_smtp_username, settings.email_smtp_password)
            server.send_message(message)


async def send_email(recipient: str, subject: str, text_body: str, html_body: str | None = None) -> None:
    if not email_smtp_configured():
        raise RuntimeError("SMTP is not configured")
    await asyncio.to_thread(_send_sync, recipient, subject, text_body, html_body)

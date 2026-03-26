"""Async SMTP sender with retry/backoff, error categorization, and connection semaphore."""

import asyncio
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import aiosmtplib

from .config import AppConfig, SmtpConfig

logger = logging.getLogger(__name__)

# Errors we consider permanent (no retry)
PERMANENT_EXCEPTIONS = (
    aiosmtplib.SMTPAuthenticationError,
    aiosmtplib.SMTPRecipientsRefused,
    aiosmtplib.SMTPDataError,
)


def _is_permanent(exc: BaseException) -> bool:
    if isinstance(exc, PERMANENT_EXCEPTIONS):
        return True
    msg = str(exc).lower()
    if "5" in msg and "auth" in msg:
        return True
    if "535" in msg or "534" in msg:
        return True
    return False


async def send_email(
    config: SmtpConfig,
    *,
    to: list[str],
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    subject: str,
    body_html: str,
    from_addr: str | None = None,
    semaphore: asyncio.Semaphore | None = None,
    max_attempts: int = 3,
    backoff_base_seconds: float = 2,
    backoff_max_seconds: float = 60,
) -> tuple[bool, int, str | None]:
    """
    Send email via SMTP. Returns (success, attempts, error_message).
    Uses semaphore if provided to limit concurrent connections.
    """
    cc = cc or []
    bcc = bcc or []
    from_addr = from_addr or config.from_address
    if semaphore:
        async with semaphore:
            return await _send_impl(
                config, to=to, cc=cc, bcc=bcc, subject=subject, body_html=body_html,
                from_addr=from_addr, max_attempts=max_attempts,
                backoff_base_seconds=backoff_base_seconds, backoff_max_seconds=backoff_max_seconds,
            )
    return await _send_impl(
        config, to=to, cc=cc, bcc=bcc, subject=subject, body_html=body_html,
        from_addr=from_addr, max_attempts=max_attempts,
        backoff_base_seconds=backoff_base_seconds, backoff_max_seconds=backoff_max_seconds,
    )


async def _send_impl(
    config: SmtpConfig,
    *,
    to: list[str],
    cc: list[str],
    bcc: list[str],
    subject: str,
    body_html: str,
    from_addr: str,
    max_attempts: int = 3,
    backoff_base_seconds: float = 2,
    backoff_max_seconds: float = 60,
) -> tuple[bool, int, str | None]:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg.attach(MIMEText(body_html, "html", "utf-8"))
    recipients = list(to) + list(cc) + list(bcc)

    last_error: str | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            await aiosmtplib.send(
                msg,
                hostname=config.host,
                port=config.port,
                username=config.username or None,
                password=config.password or None,
                use_tls=config.port == 465,
                start_tls=config.starttls and config.port != 465,
                recipients=recipients,
            )
            return True, attempt, None
        except Exception as e:
            last_error = str(e)
            if _is_permanent(e):
                return False, attempt, last_error
            if attempt < max_attempts:
                delay = min(backoff_base_seconds ** attempt, backoff_max_seconds)
                await asyncio.sleep(delay)
    return False, max_attempts, last_error


def get_smtp_semaphore(config: AppConfig) -> asyncio.Semaphore:
    return asyncio.Semaphore(config.smtp.max_connections)

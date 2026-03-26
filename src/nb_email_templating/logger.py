"""Structured JSON logging with request_id tracing and secret redaction."""

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from pythonjsonlogger import jsonlogger

# Values to redact in log output
REDACT_PATTERNS = [
    (re.compile(r"token=[^&\s]+", re.I), "token=[REDACTED]"),
    (re.compile(r"password['\"]?\s*[:=]\s*['\"]?[^\s'\"]+", re.I), "password=[REDACTED]"),
    (re.compile(r"webhook_token['\"]?\s*[:=]\s*['\"]?[^\s'\"]+", re.I), "webhook_token=[REDACTED]"),
]


def redact_message(msg: str) -> str:
    for pattern, replacement in REDACT_PATTERNS:
        msg = pattern.sub(replacement, msg)
    return msg


class RedactingJsonFormatter(jsonlogger.JsonFormatter):
    def format(self, record: logging.LogRecord) -> str:
        if hasattr(record, "msg") and isinstance(record.msg, str):
            record.msg = redact_message(record.msg)
        if hasattr(record, "message") and isinstance(record.message, str):
            record.message = redact_message(record.message)
        return super().format(record)


def setup_logging(
    log_path: str,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    level: str = "INFO",
) -> None:
    """Configure root logger with JSON file handler and rotation."""
    Path(log_path).mkdir(parents=True, exist_ok=True)
    log_file = Path(log_path) / "nb-email-templating.log"
    handler = RotatingFileHandler(
        str(log_file),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    formatter = RedactingJsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    # Avoid duplicate file handlers to same path
    for h in root.handlers[:]:
        if h is not handler and isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", "") == str(log_file):
            root.removeHandler(h)


def bind_request_id(request_id: str) -> None:
    """Set request_id in logging context (e.g. contextvars)."""
    pass  # Can use contextvars; for now request_id is passed in log extra


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

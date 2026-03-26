"""YAML config loader with env var resolution and Pydantic validation."""

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


_ENV_PATTERN = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")


def _resolve_env(value: Any) -> Any:
    """Recursively resolve ${VAR} and ${VAR:-default} in strings."""
    if isinstance(value, str):
        def repl(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(2)
            out = os.environ.get(name)
            if default is not None:
                # Match shell `${VAR:-default}` semantics: use default when var is unset or empty.
                if out not in (None, ""):
                    return out
                return default
            if out is not None:
                return out
            raise ValueError(f"Environment variable {name!r} is not set and has no default")

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _resolve_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env(v) for v in value]
    return value


class RecipientsConfig(BaseModel):
    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)


class TemplateEntryConfig(BaseModel):
    file: str
    active: bool = True
    subject: str
    recipients: RecipientsConfig = Field(default_factory=RecipientsConfig)


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8025
    public_base_url: str = Field(
        default="",
        description="Optional public origin for the webhook URL on the overview page (e.g. https://alerts.example.com) when the dashboard is opened on a different host than Beezkeeper uses.",
    )
    shutdown_timeout_seconds: int = 30
    max_request_size: int = 1048576


class AuthConfig(BaseModel):
    webhook_token: str = ""
    session_cookie_name: str = "nb_email_session"
    session_max_age_seconds: int = 86400


class SmtpConfig(BaseModel):
    host: str = ""
    port: int = 587
    starttls: bool = True
    username: str = ""
    password: str = ""
    from_address: str = ""
    max_connections: int = 5


class DedupConfig(BaseModel):
    window_seconds: int = 3600


class DataRetentionConfig(BaseModel):
    days: int = 90
    cleanup_hour: int = 3


class RetryConfig(BaseModel):
    max_attempts: int = 3
    backoff_base_seconds: int = 2
    backoff_max_seconds: int = 60
    recovery_timeout_seconds: int = 300


class RenderingConfig(BaseModel):
    template_render_timeout_seconds: int = 5


class TestToolsConfig(BaseModel):
    rate_limit_per_minute: int = 5


class LoggingConfig(BaseModel):
    path: str = "/var/log/nb-email-templating"
    max_bytes: int = 10485760
    backup_count: int = 5
    level: str = "INFO"
    format: str = "json"


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    smtp: SmtpConfig = Field(default_factory=SmtpConfig)
    dedup: DedupConfig = Field(default_factory=DedupConfig)
    data_retention: DataRetentionConfig = Field(default_factory=DataRetentionConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    rendering: RenderingConfig = Field(default_factory=RenderingConfig)
    test_tools: TestToolsConfig = Field(default_factory=TestToolsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    templates: dict[str, TemplateEntryConfig] = Field(default_factory=dict)


def load_config(path: str | Path) -> AppConfig:
    """Load YAML config, resolve env vars, validate with Pydantic."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    raw = yaml.safe_load(path.read_text()) or {}
    resolved = _resolve_env(raw)
    return AppConfig.model_validate(resolved)

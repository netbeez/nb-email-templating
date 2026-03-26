"""Tests for config environment variable resolution."""

import pytest

from nb_email_templating.config import _resolve_env


def test_resolve_env_uses_default_when_unset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SMTP_USERNAME", raising=False)
    out = _resolve_env("${SMTP_USERNAME:-fallback-user}")
    assert out == "fallback-user"


def test_resolve_env_uses_default_when_empty(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SMTP_USERNAME", "")
    out = _resolve_env("${SMTP_USERNAME:-fallback-user}")
    assert out == "fallback-user"


def test_resolve_env_keeps_non_empty_value(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SMTP_USERNAME", "real-user")
    out = _resolve_env("${SMTP_USERNAME:-fallback-user}")
    assert out == "real-user"

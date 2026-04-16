"""Pytest fixtures for nb-email-templating."""

import os
from pathlib import Path

import pytest
from starlette.testclient import TestClient

# Use example config for tests (env defaults avoid missing vars)
os.environ.setdefault("NB_EMAIL_WEBHOOK_TOKEN", "test-token")
os.environ.setdefault("SMTP_USERNAME", "")
os.environ.setdefault("SMTP_PASSWORD", "")


@pytest.fixture
def config_path():
    return str(Path(__file__).parent.parent / "config" / "config.example.yaml")


@pytest.fixture
def data_dir(tmp_path):
    return str(tmp_path / "data")


@pytest.fixture
def database_url(data_dir):
    return f"sqlite+aiosqlite:///{data_dir}/events.db"


@pytest.fixture
def client(config_path, data_dir, database_url):
    """FastAPI test client with overridden config and DB paths (runs ASGI lifespan)."""
    os.environ["CONFIG_PATH"] = config_path
    os.environ["DATA_DIR"] = data_dir
    os.environ["DATABASE_URL"] = database_url
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    from nb_email_templating.main import app

    with TestClient(app) as tc:
        yield tc

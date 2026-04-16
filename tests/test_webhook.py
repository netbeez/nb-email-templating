"""Webhook HTTP behavior."""

import pytest


@pytest.mark.asyncio
async def test_webhook_connectivity_without_data(client):
    """Dashboard probe: empty object or omitted data must return 200 without processing."""
    r = await client.post("/webhook?token=test-token", json={})
    assert r.status_code == 200

    r2 = await client.post("/webhook?token=test-token", json={"data": None})
    assert r2.status_code == 200

"""Webhook HTTP behavior."""


def test_webhook_connectivity_without_data(client):
    """Dashboard probe: empty object or omitted data must return 200 without processing."""
    r = client.post("/webhook?token=test-token", json={})
    assert r.status_code == 200

    r2 = client.post("/webhook?token=test-token", json={"data": None})
    assert r2.status_code == 200

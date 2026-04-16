"""Tests for JSON:API payload parsing."""

import pytest

from nb_email_templating.parser import parse_webhook_payload


def test_single_alert():
    payload = {
        "data": {
            "id": "12345",
            "type": "alert",
            "attributes": {
                "event_type": "ALERT_OPEN",
                "message": "Packet loss exceeded",
                "destination": "8.8.8.8",
            },
        }
    }
    out = parse_webhook_payload(payload)
    assert out["event_id"] == "12345"
    assert out["event_type"] == "ALERT_OPEN"
    assert out["data_type"] == "alert"
    assert out["attributes"]["message"] == "Packet loss exceeded"
    assert len(out["alerts"]) == 1
    assert out["is_aggregate"] is False
    assert out["aggregate_count"] == 1


def test_single_incident():
    payload = {
        "data": {
            "id": "789-1709712000000",
            "type": "incident",
            "attributes": {
                "event": "INCIDENT_OPEN",
                "message": "Multiple failures",
                "url": "https://netbeez.example.com/incidents/789",
            },
        }
    }
    out = parse_webhook_payload(payload)
    assert out["event_id"] == "789-1709712000000"
    assert out["event_type"] == "INCIDENT_OPEN"
    assert out["data_type"] == "incident"
    assert out["attributes"]["url"] == "https://netbeez.example.com/incidents/789"
    assert out["is_aggregate"] is False
    assert out["aggregate_count"] == 1


def test_aggregate_alerts():
    payload = {
        "data": [
            {"id": "12345", "type": "alert", "attributes": {"event_type": "ALERT_OPEN", "message": "A"}},
            {"id": "12346", "type": "alert", "attributes": {"event_type": "ALERT_OPEN", "message": "B"}},
        ]
    }
    out = parse_webhook_payload(payload)
    assert out["event_type"] == "ALERT_OPEN"
    assert out["data_type"] == "alert"
    assert len(out["alerts"]) == 2
    assert len(out["event_id"]) == 64  # sha256 hex
    assert out["attributes"]["message"] == "A"
    assert out["is_aggregate"] is True
    assert out["aggregate_count"] == 2


def test_aggregate_event_type_from_first_alert():
    payload = {
        "data": [
            {"id": "1", "type": "alert", "attributes": {"event_type": "ALERT_OPEN", "message": "first"}},
            {"id": "2", "type": "alert", "attributes": {"event_type": "ALERT_CLEARED", "message": "second"}},
        ]
    }
    out = parse_webhook_payload(payload)
    assert out["event_type"] == "ALERT_OPEN"


def test_aggregate_single_item_array():
    """Beezkeeper may send a one-element data array; still expose aggregate_count."""
    payload = {
        "data": [
            {"id": "12345", "type": "alert", "attributes": {"event_type": "ALERT_OPEN", "message": "Only"}},
        ]
    }
    out = parse_webhook_payload(payload)
    assert len(out["alerts"]) == 1
    assert out["attributes"]["message"] == "Only"
    assert out["is_aggregate"] is False
    assert out["aggregate_count"] == 1


def test_missing_data():
    with pytest.raises(ValueError, match="Missing 'data'"):
        parse_webhook_payload({})


def test_empty_data_array():
    with pytest.raises(ValueError, match="empty"):
        parse_webhook_payload({"data": []})

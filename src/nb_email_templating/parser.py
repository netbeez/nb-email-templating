"""JSON:API payload normalizer for alerts and incidents."""

import hashlib
from typing import Any

from pydantic import BaseModel, Field


class AlertAttributes(BaseModel):
    severity: int | None = None
    severity_name: str | None = None
    alert_dedup_id: int | None = None
    event_type: str | None = None
    agent: str | None = None
    agent_description: str | None = None
    target: str | None = None
    wifi_profile: str | None = None
    destination: str | None = None
    message: str | None = None
    test_type: str | None = None
    alert_ts: int | None = None


class IncidentAttributes(BaseModel):
    incident_id: int | None = None
    event: str | None = None
    event_ts: int | None = None
    agent: str | None = None
    agent_description: str | None = None
    agent_id: int | None = None
    target: str | None = None
    target_id: int | None = None
    wifi_profile: str | None = None
    wifi_profile_id: int | None = None
    url: str | None = None
    message: str | None = None
    incident_ts: int | None = None


class DataAlert(BaseModel):
    id: str
    type: str = "alert"
    attributes: AlertAttributes | dict[str, Any] = Field(default_factory=dict)


class DataIncident(BaseModel):
    id: str
    type: str = "incident"
    attributes: IncidentAttributes | dict[str, Any] = Field(default_factory=dict)


def _normalize_attributes(raw: dict[str, Any]) -> dict[str, Any]:
    """Ensure attributes is a dict (may come as object or missing)."""
    if not raw:
        return {}
    return dict(raw) if isinstance(raw, dict) else {}


def parse_webhook_payload(body: dict[str, Any]) -> dict[str, Any]:
    """
    Parse JSON:API payload and return normalized structure for rendering.
    Returns dict with: event_id, event_type, data_type, attributes, alerts (list for template),
    is_aggregate (True when data was an array with more than one alert), aggregate_count.
    For single alert/incident: alerts has one element (attributes-style).
    For aggregate alerts: alerts is list of attribute dicts; attributes mirrors the first alert;
    event_id is hash of sorted ids.
    """
    data = body.get("data")
    if data is None:
        raise ValueError("Missing 'data' in payload")

    # Array = aggregate alerts
    if isinstance(data, list):
        if not data:
            raise ValueError("Payload 'data' array is empty")
        ids = []
        alerts_list = []
        event_type: str | None = None
        for item in data:
            if not isinstance(item, dict):
                raise ValueError("Aggregate data item is not an object")
            id_val = item.get("id")
            if not id_val:
                raise ValueError("Aggregate alert missing 'id'")
            ids.append(str(id_val))
            attrs = _normalize_attributes(item.get("attributes") or {})
            et = attrs.get("event_type") or "ALERT_OPEN"
            if event_type is None:
                event_type = et
            alerts_list.append({"id": id_val, "attributes": attrs, "event_type": et})
        event_type = event_type or "ALERT_OPEN"
        event_id = hashlib.sha256("|".join(sorted(ids)).encode()).hexdigest()
        n = len(alerts_list)
        return {
            "event_id": event_id,
            "event_type": event_type,
            "data_type": "alert",
            "attributes": alerts_list[0]["attributes"],
            "alerts": [a["attributes"] for a in alerts_list],
            "is_aggregate": n > 1,
            "aggregate_count": n,
        }

    # Single object
    if not isinstance(data, dict):
        raise ValueError("Payload 'data' is not an object or array")

    data_id = data.get("id")
    if not data_id:
        raise ValueError("Payload 'data' missing 'id'")
    data_type = (data.get("type") or "alert").lower()
    attributes = _normalize_attributes(data.get("attributes") or {})

    if data_type == "alert":
        event_type = attributes.get("event_type") or "ALERT_OPEN"
        return {
            "event_id": str(data_id),
            "event_type": event_type,
            "data_type": "alert",
            "attributes": attributes,
            "alerts": [attributes],
            "is_aggregate": False,
            "aggregate_count": 1,
        }
    if data_type == "incident":
        event_type = attributes.get("event") or "INCIDENT_OPEN"
        return {
            "event_id": str(data_id),
            "event_type": event_type,
            "data_type": "incident",
            "attributes": attributes,
            "alerts": [attributes],
            "is_aggregate": False,
            "aggregate_count": 1,
        }
    raise ValueError(f"Unknown data type: {data_type}")

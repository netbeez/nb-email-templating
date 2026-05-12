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


def _aggregate_entity_type_label(entity_type: str | None) -> str:
    labels = {
        "agent": "Agent",
        "target": "Target",
        "wifi_profile": "WiFi Profile",
        "scheduled_test": "Scheduled Test",
    }
    return labels.get((entity_type or "").lower(), "Aggregate")


def _aggregate_entity_name(attrs: dict[str, Any], entity_type: str | None) -> str:
    entity_type = (entity_type or "").lower()
    if entity_type == "agent":
        return str(attrs.get("agent") or "")
    if entity_type == "target":
        return str(attrs.get("target") or "")
    if entity_type == "wifi_profile":
        return str(attrs.get("wifi_profile") or "")
    if entity_type == "scheduled_test":
        return str(attrs.get("destination") or attrs.get("message") or "")
    return str(attrs.get("agent") or attrs.get("target") or attrs.get("wifi_profile") or attrs.get("destination") or "")


def _aggregate_metadata(attrs: dict[str, Any]) -> dict[str, Any]:
    entity_type = attrs.get("aggregation_entity_type")
    entity_label = _aggregate_entity_type_label(entity_type)
    entity_name = _aggregate_entity_name(attrs, entity_type)
    test_counts = attrs.get("test_counts") or {}
    return {
        "aggregation_entity_type": entity_type,
        "aggregation_entity_type_label": entity_label,
        "aggregation_entity_name": entity_name,
        "aggregate_entity_type_label": entity_label,
        "aggregate_entity_name": entity_name,
        "test_counts": test_counts,
    }


def _incident_metadata(attrs: dict[str, Any]) -> dict[str, Any]:
    if attrs.get("wifi_profile"):
        entity_type = "wifi_profile"
        entity_label = "WiFi"
        entity_name = str(attrs.get("wifi_profile") or "")
    elif attrs.get("target"):
        entity_type = "target"
        entity_label = "Target"
        entity_name = str(attrs.get("target") or "")
    elif attrs.get("agent"):
        entity_type = "agent"
        entity_label = "Agent"
        entity_name = str(attrs.get("agent") or "")
    else:
        entity_type = None
        entity_label = "Incident"
        entity_name = ""
    return {
        "incident_entity_type": entity_type,
        "incident_entity_type_label": entity_label,
        "incident_entity_name": entity_name,
    }


def parse_webhook_payload(body: dict[str, Any]) -> dict[str, Any]:
    """
    Parse JSON:API payload and return normalized structure for rendering.
    Returns dict with: event_id, event_type, data_type, attributes, alerts (list for template),
    is_aggregate (True when data was an array), aggregate_count.
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
        for item in data:
            if not isinstance(item, dict):
                raise ValueError("Aggregate data item is not an object")
            id_val = item.get("id")
            if not id_val:
                raise ValueError("Aggregate alert missing 'id'")
            ids.append(str(id_val))
            attrs = _normalize_attributes(item.get("attributes") or {})
            et = attrs.get("event_type") or "ALERT_OPEN"
            attrs.setdefault("event_type", et)
            alerts_list.append({"id": id_val, "attributes": attrs, "event_type": et})
        event_id = hashlib.sha256("|".join(sorted(ids)).encode()).hexdigest()
        n = len(alerts_list)
        first_attrs = alerts_list[0]["attributes"]
        return {
            "event_id": event_id,
            "event_type": "ALERT_AGGREGATE",
            "data_type": "alert",
            "attributes": first_attrs,
            "alerts": [a["attributes"] for a in alerts_list],
            "is_aggregate": True,
            "aggregate_count": n,
            **_aggregate_metadata(first_attrs),
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
            **_incident_metadata(attributes),
        }
    raise ValueError(f"Unknown data type: {data_type}")

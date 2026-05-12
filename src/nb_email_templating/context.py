"""Build Jinja render context for webhook delivery and previews."""

from typing import Any


def build_render_context(parsed: dict[str, Any], template_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Merge optional config `template_context` with normalized webhook fields.
    Webhook fields take precedence on key collision.
    """
    base = dict(template_context or {})
    base.update(
        {
            "event_type": parsed.get("event_type") or "_fallback",
            "event_id": parsed.get("event_id"),
            "data_type": parsed.get("data_type"),
            "attributes": parsed.get("attributes") or {},
            "alerts": parsed.get("alerts") or [],
            "is_aggregate": parsed.get("is_aggregate", False),
            "aggregate_count": parsed.get("aggregate_count", 1),
            "aggregation_entity_type": parsed.get("aggregation_entity_type"),
            "aggregation_entity_type_label": parsed.get("aggregation_entity_type_label") or "Aggregate",
            "aggregation_entity_name": parsed.get("aggregation_entity_name") or "",
            "aggregate_entity_type_label": parsed.get("aggregate_entity_type_label") or "Aggregate",
            "aggregate_entity_name": parsed.get("aggregate_entity_name") or "",
            "test_counts": parsed.get("test_counts") or {},
            "incident_entity_type": parsed.get("incident_entity_type"),
            "incident_entity_type_label": parsed.get("incident_entity_type_label") or "Incident",
            "incident_entity_name": parsed.get("incident_entity_name") or "",
        }
    )
    return base

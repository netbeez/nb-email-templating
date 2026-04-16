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
        }
    )
    return base

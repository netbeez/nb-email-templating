"""Render context builder."""

import asyncio

from nb_email_templating.context import build_render_context
from nb_email_templating.config import load_config
from nb_email_templating.parser import parse_webhook_payload
from nb_email_templating.renderer import TemplateRenderer


def test_build_render_context_merges_template_context():
    parsed = {
        "event_type": "ALERT_OPEN",
        "event_id": "1",
        "data_type": "alert",
        "attributes": {"message": "m"},
        "alerts": [{"message": "m"}],
        "is_aggregate": False,
        "aggregate_count": 1,
    }
    ctx = build_render_context(parsed, {"staff_sop_url": "https://sop.example/internal"})
    assert ctx["staff_sop_url"] == "https://sop.example/internal"
    assert ctx["attributes"]["message"] == "m"
    assert ctx["aggregate_count"] == 1


def test_build_render_context_exposes_aggregate_metadata():
    parsed = {
        "event_type": "ALERT_AGGREGATE",
        "event_id": "abc",
        "data_type": "alert",
        "attributes": {"message": "m"},
        "alerts": [{"event_type": "ALERT_OPEN", "message": "m"}],
        "is_aggregate": True,
        "aggregate_count": 1,
        "aggregation_entity_type": "agent",
        "aggregation_entity_type_label": "Agent",
        "aggregation_entity_name": "NYC Agent 1",
        "test_counts": {"1": {"success": 1, "fail": 1}},
    }
    ctx = build_render_context(parsed)
    assert ctx["event_type"] == "ALERT_AGGREGATE"
    assert ctx["aggregation_entity_type_label"] == "Agent"
    assert ctx["aggregation_entity_name"] == "NYC Agent 1"
    assert ctx["test_counts"] == {"1": {"success": 1, "fail": 1}}


def test_build_render_context_exposes_incident_metadata():
    parsed = {
        "event_type": "INCIDENT_OPEN",
        "event_id": "inc-1",
        "data_type": "incident",
        "attributes": {"message": "m"},
        "alerts": [{"message": "m"}],
        "is_aggregate": False,
        "aggregate_count": 1,
        "incident_entity_type": "target",
        "incident_entity_type_label": "Target",
        "incident_entity_name": "api.example.com",
    }
    ctx = build_render_context(parsed)
    assert ctx["incident_entity_type"] == "target"
    assert ctx["incident_entity_type_label"] == "Target"
    assert ctx["incident_entity_name"] == "api.example.com"


def test_build_render_context_webhook_fields_override_template_context():
    parsed = {
        "event_type": "ALERT_OPEN",
        "event_id": "1",
        "data_type": "alert",
        "attributes": {},
        "alerts": [],
        "is_aggregate": False,
        "aggregate_count": 1,
    }
    ctx = build_render_context(parsed, {"event_type": "SHOULD_NOT_WIN", "staff_sop_url": "x"})
    assert ctx["event_type"] == "ALERT_OPEN"
    assert ctx["staff_sop_url"] == "x"


def test_rewrite_url_origin_filter_registered():
    from pathlib import Path

    root = Path(__file__).parent.parent / "email_templates"
    r = TemplateRenderer(root, template_config={})
    out = r.env.from_string("{{ u | rewrite_url_origin }}").render(
        u="https://fsntgd-old.example.com/incidents/1",
        netbeez_dashboard_url="https://nbz.example.com",
    )
    assert out == "https://nbz.example.com/incidents/1"


def test_rewrite_url_origin_without_base_leaves_url():
    from pathlib import Path

    root = Path(__file__).parent.parent / "email_templates"
    r = TemplateRenderer(root, template_config={})
    out = r.env.from_string("{{ u | rewrite_url_origin }}").render(
        u="https://legacy.example/path?q=1",
        netbeez_dashboard_url="",
    )
    assert out == "https://legacy.example/path?q=1"


def test_aggregate_template_and_subject_render():
    from pathlib import Path

    root = Path(__file__).parent.parent
    config = load_config(root / "config" / "config.example.yaml")
    renderer = TemplateRenderer(root / "email_templates", template_config=config.templates)
    ctx = build_render_context(
        {
            "event_type": "ALERT_AGGREGATE",
            "event_id": "aggregate-id",
            "data_type": "alert",
            "attributes": {
                "event_type": "ALERT_OPEN",
                "message": "HTTP request timed out",
                "agent": "NYC Agent 1",
                "aggregation_entity_type": "agent",
                "test_counts": {"3": {"success": 2, "fail": 1, "warning": 0, "paused": 0, "unknown": 0}},
            },
            "alerts": [
                {
                    "event_type": "ALERT_OPEN",
                    "severity_name": "critical",
                    "message": "HTTP request timed out",
                    "agent": "NYC Agent 1",
                    "target": "api.example.com",
                    "test_type": "HttpTest",
                    "alert_ts": 1711626000000,
                },
                {
                    "event_type": "ALERT_CLEARED",
                    "severity_name": "informational",
                    "message": "DNS lookups succeeding",
                    "agent": "NYC Agent 1",
                    "target": "Corporate DNS",
                    "test_type": "DnsTest",
                    "alert_ts": 1711626060000,
                },
            ],
            "is_aggregate": True,
            "aggregate_count": 2,
            "aggregation_entity_type": "agent",
            "aggregation_entity_type_label": "Agent",
            "aggregation_entity_name": "NYC Agent 1",
            "test_counts": {"3": {"success": 2, "fail": 1, "warning": 0, "paused": 0, "unknown": 0}},
        }
    )
    subject = renderer.render_subject("ALERT_AGGREGATE", ctx)
    html, error = asyncio.run(renderer.render_body("ALERT_AGGREGATE", ctx))
    assert subject == "[NB] - Agent Aggregate Alert - NYC Agent 1 - Count: 2"
    assert error is None
    assert "Agent aggregate: NYC Agent 1" in html
    assert "Cleared" in html


def test_incident_subject_renders_per_kind():
    from pathlib import Path

    root = Path(__file__).parent.parent
    config = load_config(root / "config" / "config.example.yaml")
    renderer = TemplateRenderer(root / "email_templates", template_config=config.templates)

    samples = [
        (
            "Agent",
            "demo-agent-01",
            {
                "agent": "demo-agent-01",
                "agent_id": 11,
                "message": "Agent incident",
            },
        ),
        (
            "Target",
            "api.example.com",
            {
                "target": "api.example.com",
                "target_id": 101,
                "message": "Target incident",
            },
        ),
        (
            "WiFi",
            "Corporate WiFi",
            {
                "wifi_profile": "Corporate WiFi",
                "wifi_profile_id": 301,
                "message": "WiFi incident",
            },
        ),
    ]

    for label, entity_name, attrs in samples:
        parsed = parse_webhook_payload(
            {
                "data": {
                    "id": f"incident-{label.lower()}",
                    "type": "incident",
                    "attributes": {
                        "event": "INCIDENT_OPEN",
                        "incident_id": 42,
                        "url": "https://app.netbeez.net/incidents/42",
                        "incident_ts": 1711626000000,
                        **attrs,
                    },
                }
            }
        )
        ctx = build_render_context(parsed)
        subject = renderer.render_subject("INCIDENT_OPEN", ctx)
        assert label in subject
        assert entity_name in subject

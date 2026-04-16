"""Render context builder."""

from nb_email_templating.context import build_render_context


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

    from nb_email_templating.renderer import TemplateRenderer

    root = Path(__file__).parent.parent / "email_templates"
    r = TemplateRenderer(root, template_config={})
    out = r.env.from_string("{{ u | rewrite_url_origin }}").render(
        u="https://fsntgd-old.example.com/incidents/1",
        netbeez_dashboard_url="https://nbz.example.com",
    )
    assert out == "https://nbz.example.com/incidents/1"


def test_rewrite_url_origin_without_base_leaves_url():
    from pathlib import Path

    from nb_email_templating.renderer import TemplateRenderer

    root = Path(__file__).parent.parent / "email_templates"
    r = TemplateRenderer(root, template_config={})
    out = r.env.from_string("{{ u | rewrite_url_origin }}").render(
        u="https://legacy.example/path?q=1",
        netbeez_dashboard_url="",
    )
    assert out == "https://legacy.example/path?q=1"

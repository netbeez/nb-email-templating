import asyncio
import shutil
from pathlib import Path
from types import SimpleNamespace

import yaml

from nb_email_templating.config import load_config
from nb_email_templating import template_editor


class DummyRequest:
    def __init__(self, state, body):
        self.app = SimpleNamespace(state=state)
        self._body = body

    async def json(self):
        return self._body


async def test_save_template_recipient_only_change_does_not_rewrite_template(tmp_path, monkeypatch):
    root = Path(__file__).parent.parent
    config_path = tmp_path / "config.yaml"
    templates_dir = tmp_path / "email_templates"
    templates_dir.mkdir()

    shutil.copy(root / "config" / "config.example.yaml", config_path)
    template_path = templates_dir / "incident_open.html.j2"
    content = (root / "email_templates" / "incident_open.html.j2").read_text(encoding="utf-8")
    template_path.write_text(content, encoding="utf-8")

    original_write_text_atomic = template_editor._write_text_atomic

    def write_text_atomic(path, new_content, *, permission_detail):
        if path == template_path:
            raise AssertionError("recipient-only save should not rewrite the template")
        return original_write_text_atomic(path, new_content, permission_detail=permission_detail)

    monkeypatch.setattr(template_editor, "_write_text_atomic", write_text_atomic)

    state = SimpleNamespace(
        config=load_config(config_path),
        config_path=str(config_path),
        email_templates_dir=str(templates_dir),
        reload_lock=asyncio.Lock(),
    )
    request = DummyRequest(
        state,
        {
            "content": content,
            "subject": None,
            "recipients": {"to": ["noc@example.com"], "cc": [], "bcc": []},
        },
    )

    response = await template_editor.save_template(request, "incident_open.html.j2", True)

    assert response == {"ok": True}
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert raw["templates"]["INCIDENT_OPEN"]["recipients"]["to"] == ["noc@example.com"]

"""Jinja2 SandboxedEnvironment with bytecode cache, timeout, and fallback."""

import asyncio
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from jinja2 import FileSystemBytecodeCache, FileSystemLoader, TemplateNotFound, UndefinedError, pass_context
from jinja2.exceptions import TemplateSyntaxError
from jinja2.sandbox import SandboxedEnvironment


DEFAULT_SUBJECT_FALLBACK = "[NetBeez] {event_type} Notification"


def _rewrite_url_origin(url: str, new_origin: str) -> str:
    """Replace scheme/host of url with the origin from new_origin (e.g. configured friendly NetBeez hostname)."""
    if not url or not (new_origin or "").strip():
        return url or ""
    u = urlparse(url.strip())
    o = new_origin.strip()
    if "://" not in o:
        o = "https://" + o
    b = urlparse(o)
    if not b.netloc:
        return url
    scheme = b.scheme or u.scheme or "https"
    return urlunparse((scheme, b.netloc, u.path or "", u.params, u.query, u.fragment))


@pass_context
def _rewrite_url_origin_filter(context: Any, url: Any) -> str:
    if url is None:
        return ""
    base = context.get("netbeez_dashboard_url") or ""
    return _rewrite_url_origin(str(url), base)


class TemplateRenderer:
    def __init__(
        self,
        templates_dir: str | Path,
        bytecode_cache_dir: str | Path | None = None,
        render_timeout_seconds: float = 5,
        template_config: dict[str, Any] | None = None,
    ):
        self.templates_dir = Path(templates_dir)
        self.render_timeout = render_timeout_seconds
        self.template_config = template_config or {}
        cache_dir = Path(bytecode_cache_dir) if bytecode_cache_dir else self.templates_dir / ".jinja2_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.env = SandboxedEnvironment(
            loader=FileSystemLoader(str(self.templates_dir)),
            bytecode_cache=FileSystemBytecodeCache(str(cache_dir)),
            auto_reload=False,
        )
        self.env.filters["rewrite_url_origin"] = _rewrite_url_origin_filter

    def _render_sync(self, template_name: str, context: dict[str, Any]) -> str:
        template = self.env.get_template(template_name)
        return template.render(**context)

    async def render_body(self, event_type: str, context: dict[str, Any]) -> tuple[str, str | None]:
        """
        Render email body. Returns (html_body, error).
        Tries event-type template then fallback; on exception returns (fallback_html, error_msg).
        """
        config = self.template_config
        entry = config.get(event_type) or config.get("_fallback")
        template_file = entry.file if entry else "_fallback.html.j2"
        try:
            html = await asyncio.wait_for(
                asyncio.to_thread(self._render_sync, template_file, context),
                timeout=self.render_timeout,
            )
            return html, None
        except (TemplateSyntaxError, UndefinedError, TemplateNotFound, asyncio.TimeoutError) as e:
            fallback_entry = config.get("_fallback")
            fallback_file = fallback_entry.file if fallback_entry else "_fallback.html.j2"
            try:
                fallback_html = await asyncio.wait_for(
                    asyncio.to_thread(self._render_sync, fallback_file, {**context, "event_type": event_type}),
                    timeout=self.render_timeout,
                )
                return fallback_html, str(e)
            except Exception as e2:
                return "", str(e2) or str(e)

    def render_subject(self, event_type: str, context: dict[str, Any]) -> str:
        """Render subject line; on failure return static fallback."""
        entry = self.template_config.get(event_type) or self.template_config.get("_fallback")
        subject_tpl = entry.subject if entry else DEFAULT_SUBJECT_FALLBACK
        try:
            return self._render_sync_from_string(subject_tpl, context)
        except Exception:
            return DEFAULT_SUBJECT_FALLBACK.format(event_type=event_type)

    def _render_sync_from_string(self, source: str, context: dict[str, Any]) -> str:
        template = self.env.from_string(source)
        return template.render(**context)

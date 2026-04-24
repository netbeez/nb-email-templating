# nb-email-templating

Standalone Python (FastAPI + Jinja2) service that receives NetBeez webhook notifications, renders event-specific email templates, and sends via SMTP with retry. Includes a web dashboard and optional Docker deployment.

## Overview

- **nb-api** sends webhook POSTs (JSON:API) to this service.
- The service validates the payload, deduplicates by event ID, renders the matching Jinja2 template, and sends email via SMTP.
- A built-in dashboard shows template inventory, event history, config (redacted), and test tools.

**Important:** If you use both **nb-api’s built-in email notifications** (Settings → Notification Integrations → SMTP) and this webhook-based service, you will get **duplicate emails** for every alert/incident. Disable the built-in SMTP notification channel when using this service (or the reverse).

## Prerequisites

- Python 3.11+
- Docker Engine 20.10+ and Docker Compose v2 (for containerized run)
- SMTP relay or mail server reachable from the service
- Network reachability from the Beezkeeper server (nb-api) to this service
- A shared webhook auth token (configured in nb-api and in this service’s config)

## Quick start

1. Download the project and go to the project root.

   **Git clone** (recommended):

   ```bash
   git clone https://github.com/netbeez/nb-email-templating.git
   cd nb-email-templating
   ```

   **Tarball** (optional, if you prefer not to use Git): download the archive for your branch or tag, then extract and enter the directory (GitHub archives unpack to a folder named `<repo>-<ref>`):

   ```bash
   curl -fsSL -o nb-email-templating.tar.gz 'https://github.com/netbeez/nb-email-templating/archive/refs/heads/main.tar.gz'
   tar xzf nb-email-templating.tar.gz
   cd nb-email-templating-main
   ```

2. If you run with Docker Compose, create an empty `.env` in the project root so Compose does not fail on the `env_file: .env` entry in `docker-compose.yml` (you can add real variables to this file later):

   ```bash
   touch .env
   ```

3. Copy the example config and set token + SMTP via env or edit:

   ```bash
   cp config/config.example.yaml config/config.yaml
   export NB_EMAIL_WEBHOOK_TOKEN=your-secret-token
   export SMTP_USERNAME=your-smtp-user
   export SMTP_PASSWORD=your-smtp-password
   ```

4. Run with Docker (Compose reads the project `.env` and passes values into the container; see `docker-compose.yml`):

   ```bash
   docker compose up -d
   ```
   Or run locally (create a venv first):
   ```bash
   pip install -e .
   uvicorn nb_email_templating.main:app --host 0.0.0.0 --port 8025
   ```
5. Check health: `GET http://localhost:8025/health`

## Configuration

See `config/config.example.yaml` for all options. Main sections:

- **server**: host, port, optional `public_base_url` (for webhook URL hints on the dashboard when the browser host differs from Beezkeeper’s), shutdown timeout, max webhook payload size.
- **auth**: `webhook_token` (use `${NB_EMAIL_WEBHOOK_TOKEN}` or `${VAR:-default}`), session cookie name and max age.
- **smtp**: host, port, STARTTLS, username/password (use `${SMTP_USERNAME}`, `${SMTP_PASSWORD}`), from address, max connections.
- **dedup**: `window_seconds`.
- **data_retention**: `days`, `cleanup_hour`.
- **retry**: max attempts, backoff, recovery timeout for stuck events.
- **rendering**: template render timeout.
- **test_tools**: rate limit per minute.
- **logging**: log directory, rotation (`max_bytes`, `backup_count`), level, format (e.g. JSON).
- **template_context**: optional string key/value map merged into every email render context (e.g. `staff_sop_url`, `netbeez_dashboard_url`). The dashboard footer and incident buttons can use these; `netbeez_dashboard_url` also drives the `rewrite_url_origin` Jinja filter to swap the NetBeez host in `attributes.url`.
- **templates**: per-event-type file, subject, recipients (to/cc/bcc), active flag.

Environment variable resolution: `${VAR}` and `${VAR:-default}` are replaced from the environment before Pydantic validation. Missing required vars (no default) cause startup failure.

## Network deployment

- **Inbound**: Beezkeeper nb-api → this service (e.g. TCP 8025), and admin browser → this service (8025).
- **Outbound**: This service → SMTP server (e.g. 587 or 465).

Configure the webhook URL in nb-api to point at this service (same host or separate). Ensure TCP 8025 is reachable from nb-api to the email service host (IP or FQDN).

## Configuring webhooks in NetBeez

1. Settings → Notification Integrations → Webhooks.
2. Create an **alert** webhook: URL `http://<email-service-host>:8025/webhook?token=<your-secret-token>`, notification type **alert**, serializer **Integrations::JsonApiAlertSerializer**.
3. Create an **incident** webhook with the same URL, notification type **incident**, serializer **Integrations::JsonApiIncidentSerializer**.
4. Assign both webhooks to the desired agents/targets/wifi profiles.

## Webhook payload reference

Payloads follow JSON:API from nb-api:

- **Single alert**: `{ "data": { "id", "type": "alert", "attributes": { "event_type", "message", "agent", "destination", "alert_ts", ... } } }`
- **Aggregate alerts**: `{ "data": [ { "id", "type": "alert", "attributes": { ... } }, ... ] }`
- **Incident**: `{ "data": { "id", "type": "incident", "attributes": { "event", "message", "url", "incident_ts", ... } } }`

Templates receive `event_type`, `event_id`, `data_type`, `attributes`, and `alerts` (list; one item for single alert/incident). For aggregate alert payloads (`data` as an array), `attributes` matches the first alert, `aggregate_count` is the array length, and `is_aggregate` is true when more than one alert is present. Keys from `template_context` in config are merged into the same context. All `*_ts` fields are milliseconds since epoch.

Incident templates can render a **tests** table when `attributes.tests` is present and is a list (shape depends on your NetBeez incident serializer; if the webhook does not include that array, only the summary rows and message will appear).

## Email template customization

Templates live in `email_templates/` (e.g. `alert_open.html.j2`, `incident_open.html.j2`, `_fallback.html.j2`). Use the dashboard at `/templates` to list, edit (with validation), and preview. Subject lines are configured per event type in `config.yaml`.

## Security

- **Token in URL**: The webhook token appears in the webhook URL. Prefer internal networks, HTTPS, and token rotation.
- **Secrets**: Use env vars for `NB_EMAIL_WEBHOOK_TOKEN`, `SMTP_USERNAME`, `SMTP_PASSWORD`; the service redacts them in logs and config view.
- **Dashboard**: Protected by the same token (query param or session cookie). Mutation endpoints use CSRF.
- **Templates**: Rendered in a Jinja2 sandbox; template names validated to prevent path traversal.

## Test tools (dashboard `/test`)

- **SMTP test**: Send a test email to a given address.
- **Render + send**: Choose event type, optional JSON payload, preview HTML, or send a test email. Rate-limited (default 5/min).

## Rollback

1. `docker compose stop nb-email-templating`
2. Update image tag to the previous version
3. `docker compose up -d nb-email-templating`

SQLite data and template volumes are unchanged by rollback.

## Post-deploy checklist

1. `GET /health` returns 200 with DB and logs ok.
2. Dashboard at `GET /` (with `?token=...`) shows template inventory.
3. Send a test email from `/test`.
4. Trigger a test webhook and confirm the event appears under `/events` with delivery status.

## Troubleshooting

| Symptom | Likely cause | Check |
|--------|----------------|-------|
| nb-api logs "non 200" | Unreachable or wrong token | Network and `?token=` match |
| No emails | Wrong SMTP or relay reject | `/test` SMTP tool, logs |
| 401 on webhook | Token mismatch | Webhook URL token vs `config.auth.webhook_token` |
| Duplicate emails | Both built-in SMTP and this service on | Disable one channel |

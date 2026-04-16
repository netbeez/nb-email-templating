#!/bin/sh
set -e
PORT="${UVICORN_PORT:-8025}"
if [ -n "$SSL_CERTFILE" ] && [ -n "$SSL_KEYFILE" ] && [ -f "$SSL_CERTFILE" ] && [ -f "$SSL_KEYFILE" ]; then
  exec uvicorn nb_email_templating.main:app \
    --host 0.0.0.0 \
    --port "$PORT" \
    --ssl-certfile "$SSL_CERTFILE" \
    --ssl-keyfile "$SSL_KEYFILE"
else
  exec uvicorn nb_email_templating.main:app --host 0.0.0.0 --port "$PORT"
fi
